"""D3D9 FVF declaration ABI and pinned-runtime patch regressions."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "tools" / "patch_reflex_d3d9_fvf.py"
spec = importlib.util.spec_from_file_location("reflex_fvf_patch", PATCHER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CPP = r"""
#include "reflex_d3d9_fvf.h"
#include <cassert>
#include <cstdint>
#include <vector>

static void elem(const std::vector<uint8_t> &v, size_t n,
                 uint32_t offset, uint8_t type, uint8_t usage, uint8_t index) {
    const size_t i = n * 8u;
    assert(i + 8u <= v.size());
    assert(v[i] == 0 && v[i+1] == 0);
    assert(uint32_t(v[i+2]) + (uint32_t(v[i+3]) << 8u) == offset);
    assert(v[i+4] == type && v[i+5] == 0);
    assert(v[i+6] == usage && v[i+7] == index);
}
static void check_end(const std::vector<uint8_t> &v) {
    assert(v.size() >= 8u);
    assert(v[v.size()-8] == 0xff && v[v.size()-4] == 17);
}
int main() {
    std::vector<uint8_t> v;
    // Legacy colored, textured XYZRHW quad (POSITIONT, D3DCOLOR, TEXCOORD0).
    assert(reflex_d3d9::fvf_declaration(0x004u | 0x040u | 0x100u, v));
    assert(v.size() == 32u);
    elem(v, 0, 0, 3, 9, 0);
    elem(v, 1, 16, 4, 10, 0);
    elem(v, 2, 20, 1, 5, 0);
    check_end(v);

    // XYZ + normals + diffuse + one 3D texture coordinate.
    assert(reflex_d3d9::fvf_declaration(
        0x002u | 0x010u | 0x040u | 0x100u | (1u << 16u), v));
    assert(v.size() == 40u);
    elem(v, 0, 0, 2, 0, 0);
    elem(v, 1, 12, 2, 3, 0);
    elem(v, 2, 24, 4, 10, 0);
    elem(v, 3, 28, 2, 5, 0);
    check_end(v);

    // XYZB2 plus final blend index, a normal and a 2D texcoord.
    assert(reflex_d3d9::fvf_declaration(
        0x008u | 0x1000u | 0x010u | 0x100u, v));
    assert(v.size() == 48u);
    elem(v, 0, 0, 2, 0, 0);
    elem(v, 1, 12, 0, 1, 0);
    elem(v, 2, 16, 5, 2, 0);
    elem(v, 3, 20, 2, 3, 0);
    elem(v, 4, 32, 1, 5, 0);
    check_end(v);

    assert(reflex_d3d9::fvf_declaration(0x4002u, v));
    assert(v.size() == 16u);
    elem(v, 0, 0, 3, 0, 0);
    check_end(v);

    // Malformed layouts cannot overwrite the last successful declaration.
    const auto original = v;
    assert(!reflex_d3d9::fvf_declaration(0, v));
    assert(!reflex_d3d9::fvf_declaration(0x004u | 0x010u, v));
    assert(!reflex_d3d9::fvf_declaration(0x002u | 0x1000u, v));
    assert(!reflex_d3d9::fvf_declaration(0x002u | 0x100u | (1u << 18u), v));
    assert(!reflex_d3d9::fvf_declaration(0x002u | 0x0900u, v));
    assert(v == original);
    return 0;
}
"""


def test_fvf_to_d3dvertexelement_native(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("No native C++ compiler")
    source = tmp_path / "fvf.cpp"
    binary = tmp_path / "fvf"
    source.write_text(CPP)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def kit_fixture(root):
    (root / "dx").mkdir(parents=True)
    (root / "dx" / "com.h").write_text(
        "    uint32_t d9_primary_swapchain = 0; // weak id; swap chain owns a device ref\n"
    )
    (root / "dx" / "d3d9.cpp").write_text(
        '#include "com.h"\n'
        "D9_STUB(GetVertexDeclaration, 2)\n"
        "D9_STUB(SetFVF, 2)\n"
        "D9_STUB(GetFVF, 2)\n"
        "void Dev_SetVertexDeclaration(X86 *c) {\n"
        "        d9_pipeline(dev->id).declaration = dev->current_viewport;\n"
        "    }\n"
        "    com_ret(c, D3D_OK9);\n"
        "}\n\n"
        "// (this, Type, ppQuery). A query with no GPU behind it answers immediately.\n"
    )


def test_fvf_patcher_idempotent_and_fails_closed(tmp_path):
    kit = tmp_path / "kit"
    kit_fixture(kit)
    mod.patch_fvf(kit, ROOT / "runtime")
    first = (kit / "dx" / "d3d9.cpp").read_text()
    assert first.count(mod.MARKER) == 1
    assert "void Dev_SetFVF(X86 *c)" in first
    assert "void Dev_GetFVF(X86 *c)" in first
    assert "void Dev_GetVertexDeclaration(X86 *c)" in first
    assert "dev->d9_fvf_current = 0;" in first
    assert "d9_fvf_decl" in (kit / "dx" / "com.h").read_text()
    mod.patch_fvf(kit, ROOT / "runtime")
    assert (kit / "dx" / "d3d9.cpp").read_text() == first

    bad = tmp_path / "bad"
    kit_fixture(bad)
    d3d = bad / "dx" / "d3d9.cpp"
    d3d.write_text(d3d.read_text().replace("D9_STUB(SetFVF, 2)", ""))
    with pytest.raises(RuntimeError, match="SetFVF"):
        mod.patch_fvf(bad, ROOT / "runtime")
    assert (bad / "dx" / "com.h").read_text() == (
        "    uint32_t d9_primary_swapchain = 0; // weak id; swap chain owns a device ref\n"
    )
