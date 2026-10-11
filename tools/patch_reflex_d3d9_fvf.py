#!/usr/bin/env python3
"""Implement D3D9 SetFVF/GetFVF/GetVertexDeclaration in the pinned runtime.

Reflex reaches SetFVF after programmable startup draws, but the pinned kit
does not preserve this state. Convert standard FVF declarations to real D3D9
vertex declaration COM objects, which both CPU and GPU paths already read.
Never invent a shader or mark a skipped draw as rendered.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
MARKER = "reflex-fvf-bridge-v1"


def replace_once(text: str, original: str, replacement: str, label: str) -> str:
    if text.count(original) != 1:
        raise RuntimeError(f"Expected one {label} anchor, got {text.count(original)}")
    return text.replace(original, replacement, 1)


def patch_fvf(kit: Path, runtime: Path) -> None:
    com = kit / "dx" / "com.h"
    d3d = kit / "dx" / "d3d9.cpp"
    helper = runtime / "reflex_d3d9_fvf.h"
    if not com.is_file() or not d3d.is_file() or not helper.is_file():
        raise RuntimeError("Pinned D3D9 sources or FVF header missing")
    original = d3d.read_text()
    original_com = com.read_text()
    if MARKER in original:
        if original.count(MARKER) != 1 or "d9_fvf_cached" not in original_com:
            raise RuntimeError("Partial or duplicate FVF bridge")
        if not (kit / "dx" / "reflex_d3d9_fvf.h").is_file():
            raise RuntimeError("Missing copied FVF header")
        return

    changed_com = replace_once(
        original_com,
        "    uint32_t d9_primary_swapchain = 0; // weak id; swap chain owns a device ref\n",
        "    uint32_t d9_primary_swapchain = 0; // weak id; swap chain owns a device ref\n"
        "    uint32_t d9_fvf_current = 0; // active FVF, zero with explicit declaration\n"
        "    uint32_t d9_fvf_cached = 0;  // implicit declaration cache key\n"
        "    uint32_t d9_fvf_decl = 0;    // one device-owned declaration ref\n",
        "ComObj swap-chain/fvf state",
    )
    changed = replace_once(
        original,
        '#include "com.h"\n',
        '#include "com.h"\n#include "reflex_d3d9_fvf.h"\n',
        "D3D9 include",
    )
    for stub in ("D9_STUB(GetVertexDeclaration, 2)\n",
                 "D9_STUB(SetFVF, 2)\n",
                 "D9_STUB(GetFVF, 2)\n"):
        changed = replace_once(changed, stub, "", stub.strip())

    changed = replace_once(
        changed,
        "        d9_pipeline(dev->id).declaration = dev->current_viewport;\n"
        "    }\n"
        "    com_ret(c, D3D_OK9);\n"
        "}\n\n"
        "// (this, Type, ppQuery)",
        "        d9_pipeline(dev->id).declaration = dev->current_viewport;\n"
        "        dev->d9_fvf_current = 0; // explicit declaration disables FVF state\n"
        "    }\n"
        "    com_ret(c, D3D_OK9);\n"
        "}\n\n"
        "// (this, Type, ppQuery)",
        "SetVertexDeclaration FVF reset",
    )
    implementation = r'''
// reflex-fvf-bridge-v1: preserve the legacy fixed-function vertex layout.
// (this, FVF): D3D9 uses an implicit vertex declaration for SetFVF.
void Dev_SetFVF(X86 *c) {
    ComObj *dev = this_device9(c);
    std::vector<uint8_t> declaration;
    const uint32_t fvf = arg(c, 1);
    if (!dev || !reflex_d3d9::fvf_declaration(fvf, declaration)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    ComObj *implicit = com_get(dev->d9_fvf_decl);
    if (!implicit || dev->d9_fvf_cached != fvf) {
        ComObj *fresh = com_new(K_D3D9DECL);
        if (!fresh) {
            com_ret(c, E_OUTOFMEMORY);
            return;
        }
        fresh->dev_d3d = dev->id;
        fresh->blob = std::move(declaration);
        if (!com_view(fresh, IF_D3DVERTEXDECL9)) {
            com_release(fresh);
            com_ret(c, E_OUTOFMEMORY);
            return;
        }
        const uint32_t old_id = dev->d9_fvf_decl;
        dev->d9_fvf_decl = fresh->id;
        dev->d9_fvf_cached = fvf;
        implicit = fresh;
        if (ComObj *old = com_get(old_id))
            com_release(old); // release only the device's ownership
    }
    dev->d9_fvf_current = fvf;
    dev->current_viewport = implicit->id;
    d9_pipeline(dev->id).declaration = implicit->id;
    static uint32_t logged = 0;
    if (logged++ < 12)
        LOGW("d3d9: SetFVF %08x -> declaration %u (%zu bytes)",
             fvf, implicit->id, implicit->blob.size());
    com_ret(c, D3D_OK9);
}

// (this, pFVF)
void Dev_GetFVF(X86 *c) {
    ComObj *dev = this_device9(c);
    const uint32_t out = arg(c, 1);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    wr32(out, dev->d9_fvf_current);
    com_ret(c, D3D_OK9);
}

// (this, ppDecl): the implicit declaration is a real COM declaration.
void Dev_GetVertexDeclaration(X86 *c) {
    ComObj *dev = this_device9(c);
    const uint32_t out = arg(c, 1);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    ComObj *decl = com_get(dev->current_viewport);
    uint32_t view = decl && decl->kind == K_D3D9DECL
        ? com_view(decl, IF_D3DVERTEXDECL9) : 0;
    if (decl && !view) {
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    if (view) com_addref(decl);
    com_out_ptr(out, view);
    com_ret(c, D3D_OK9);
}

'''
    changed = replace_once(
        changed,
        "// (this, Type, ppQuery). A query with no GPU behind it answers immediately.\n",
        implementation + "// (this, Type, ppQuery). A query with no GPU behind it answers immediately.\n",
        "FVF function implementation",
    )
    # Write only after all assertions succeed.
    (kit / "dx" / "reflex_d3d9_fvf.h").write_bytes(helper.read_bytes())
    com.write_text(changed_com)
    d3d.write_text(changed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=KIT)
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    patch_fvf(args.kit, args.runtime)
    print("D3D9 FVF bridge installed")


if __name__ == "__main__":
    main()
