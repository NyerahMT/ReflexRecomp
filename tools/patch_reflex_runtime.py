#!/usr/bin/env python3
"""Inject Reflex-only runtime compatibility into the pinned recomp-kit checkout."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
SOURCE = ROOT / "runtime" / "reflex_compat.cpp"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    if not (KIT / "runtime" / "CMakeLists.txt").is_file():
        raise SystemExit("kit/ is missing the pinned recomp-kit runtime")
    if not SOURCE.is_file():
        raise SystemExit(f"missing {SOURCE}")

    target = KIT / "runtime" / "reflex_compat.cpp"
    shutil.copyfile(SOURCE, target)

    cmake = KIT / "runtime" / "CMakeLists.txt"
    replace_once(
        cmake,
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp)",
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp reflex_compat.cpp)",
        "reflex_compat.cpp)",
    )

    imports = KIT / "runtime" / "imports.cpp"
    replace_once(
        imports,
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "}",
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "    extern void reflex_compat_register();\n"
        "    reflex_compat_register();\n"
        "}",
        "reflex_compat_register();",
    )

    cpu = KIT / "runtime" / "cpu.cpp"
    replace_once(
        cpu,
        "void recomp_div_error(X86 *c, uint32_t addr) {\n"
        "    LOGW(\"divide error at %08x (EAX=%08x EDX=%08x)\", addr, c->r[R_EAX], c->r[R_EDX]);\n"
        "}\n",
        "void recomp_div_error(X86 *c, uint32_t addr) {\n"
        "    auto dump4 = [](uint32_t p) -> uint32_t { return (p && gm_valid(p, 4)) ? rd32(p) : 0u; };\n"
        "    const uint32_t edi = c->r[R_EDI];\n"
        "    const uint32_t ecx = c->r[R_ECX];\n"
        "    const uint32_t ebp = c->r[R_EBP];\n"
        "    LOGW(\"divide error at %08x (EAX=%08x EDX=%08x ECX=%08x EDI=%08x EBP=%08x ESP=%08x)\",\n"
        "         addr, c->r[R_EAX], c->r[R_EDX], ecx, edi, ebp, c->r[R_ESP]);\n"
        "    if (addr == 0x00843534u || addr == 0x0084df97u || addr == 0x0088048eu) {\n"
        "        LOGW(\"hash-div state: edi[%08x,%08x,%08x,%08x,%08x,%08x,%08x] ecx[%08x,%08x,%08x,%08x,%08x,%08x,%08x]\",\n"
        "             dump4(edi + 0x00), dump4(edi + 0x04), dump4(edi + 0x08), dump4(edi + 0x0c),\n"
        "             dump4(edi + 0x10), dump4(edi + 0x14), dump4(edi + 0x18),\n"
        "             dump4(ecx + 0x00), dump4(ecx + 0x04), dump4(ecx + 0x08), dump4(ecx + 0x0c),\n"
        "             dump4(ecx + 0x10), dump4(ecx + 0x14), dump4(ecx + 0x18));\n"
        "    }\n"
        "    if (addr == 0x0084df97u) {\n"
        "        const uint32_t sp = c->r[R_ESP];\n"
        "        LOGW(\"hash-grow state: new_count=%08x xmm0=%08x xmm1=%08x grow_const=%08x load_const=%08x container[%08x,%08x,%08x,%08x,%08x,%08x,%08x]\",\n"
        "             dump4(sp + 0x18), c->xmm[0][0], c->xmm[1][0], dump4(0x009322a4u), dump4(0x00935aa8u),\n"
        "             dump4(ebp + 0x00), dump4(ebp + 0x04), dump4(ebp + 0x08), dump4(ebp + 0x0c),\n"
        "             dump4(ebp + 0x10), dump4(ebp + 0x14), dump4(ebp + 0x18));\n"
        "    }\n"
        "}\n",
        "hash-grow state:",
    )

    replace_once(
        cpu,
        "    uint32_t ret = rd32(c->r[R_ESP]);\n"
        "    // Windows maps nothing in the first 64 KB, so a call there - through a nil\n",
        "    uint32_t ret = rd32(c->r[R_ESP]);\n"
        "    if (target == 0 && ret == 0x008244e8u) {\n"
        "        const uint32_t wrapper = c->r[R_ESI];\n"
        "        const uint32_t cs = (wrapper && gm_valid(wrapper, 8)) ? rd32(wrapper) : 0;\n"
        "        const uint32_t aux = (wrapper && gm_valid(wrapper, 8)) ? rd32(wrapper + 4) : 0;\n"
        "        const uint32_t obj = (cs && gm_valid(cs + 0x18, 4)) ? rd32(cs + 0x18) : 0;\n"
        "        const uint32_t vt = (obj && gm_valid(obj, 4)) ? rd32(obj) : 0;\n"
        "        const uint32_t slot = (vt && gm_valid(vt + 0xe4, 4)) ? rd32(vt + 0xe4) : 0;\n"
        "        const uint32_t a0 = gm_valid(c->r[R_ESP] + 4, 12) ? rd32(c->r[R_ESP] + 4) : 0;\n"
        "        const uint32_t a1 = gm_valid(c->r[R_ESP] + 8, 8) ? rd32(c->r[R_ESP] + 8) : 0;\n"
        "        const uint32_t a2 = gm_valid(c->r[R_ESP] + 12, 4) ? rd32(c->r[R_ESP] + 12) : 0;\n"
        "        LOGW(\"reflex frontier 008244e8: wrapper=%08x cs=%08x aux=%08x ecx=%08x obj=%08x vt=%08x slot_e4=%08x args=%08x,%08x,%08x\",\n"
        "             wrapper, cs, aux, c->r[R_ECX], obj, vt, slot, a0, a1, a2);\n"
        "    }\n"
        "    // Windows maps nothing in the first 64 KB, so a call there - through a nil\n",
        "reflex frontier 008244e8:",
    )

    print("Applied Reflex runtime import/ABI compatibility patch")


if __name__ == "__main__":
    main()
