#!/usr/bin/env python3
"""Teach the pinned recomp-kit fallback interpreter 8-bit CMP forms.

Reflex reaches an unlisted MSVC runtime helper whose first conditional is
CMP byte ptr [...], AL. The runtime already sends unlisted code to interp_call;
supporting CMP8 lets that generic recovery path execute the helper instead of
falling back to a fabricated zero result.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERP = ROOT / "kit" / "runtime" / "interp.cpp"


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if marker in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"{INTERP}: expected one anchor for {marker!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if not INTERP.is_file():
        raise SystemExit(f"missing pinned interpreter: {INTERP}")

    text = INTERP.read_text()

    text = replace_once(
        text,
        "    case 0x90:\n        in.op = NOP;\n        break;\n",
        """    case 0x90:
        in.op = NOP;
        break;
    case 0xa1:
    case 0xa3: {
        Operand mem;
        mem.kind = 2;
        mem.disp = (int32_t)rd32(p);
        p += 4;
        in.op = MOV;
        if (b == 0xa1) {
            in.dst = reg_operand(R_EAX);
            in.src = mem;
        } else {
            in.dst = mem;
            in.src = reg_operand(R_EAX);
        }
        break;
    }
""",
        "    case 0xa1:\n    case 0xa3:",
    )

    text = replace_once(
        text,
        "    CMP,\n    TEST,\n",
        "    CMP,\n    CMP8,\n    TEST,\n",
        "    CMP8,\n",
    )

    text = replace_once(
        text,
        "    case 0x05:\n",
        """    case 0x38:
    case 0x3a: {
        Operand rm;
        if (!(n = modrm(p, rm, reg)))
            return false;
        p += n;
        in.op = CMP8;
        if (b == 0x38) {
            in.dst = rm;
            in.src = reg_operand(reg);
        } else {
            in.dst = reg_operand(reg);
            in.src = rm;
        }
        break;
    }
    case 0x05:
""",
        "    case 0x38:\n    case 0x3a:",
    )

    text = replace_once(
        text,
        """uint32_t load_mem(const X86 *c, const Operand &o) {
    uint32_t a = address_of(c, o);
    if (!readable(a, 4)) {
        snprintf(g_error, sizeof g_error, "read of %08x outside guest memory", a);
        throw Fault{};
    }
    return rd32(a);
}

""",
        """uint32_t load_mem(const X86 *c, const Operand &o) {
    uint32_t a = address_of(c, o);
    if (!readable(a, 4)) {
        snprintf(g_error, sizeof g_error, "read of %08x outside guest memory", a);
        throw Fault{};
    }
    return rd32(a);
}

uint32_t load8(const X86 *c, const Operand &o) {
    if (o.kind == 1) {
        if (o.reg < 4)
            return c->r[o.reg] & 0xffu;
        return (c->r[o.reg - 4] >> 8) & 0xffu;
    }
    if (o.kind == 3)
        return uint32_t(o.disp) & 0xffu;
    uint32_t a = address_of(c, o);
    if (!readable(a, 1)) {
        snprintf(g_error, sizeof g_error, "byte read of %08x outside guest memory", a);
        throw Fault{};
    }
    return rd8(a);
}

""",
        "uint32_t load8(const X86 *c, const Operand &o)",
    )

    text = replace_once(
        text,
        """uint32_t flag_sf(const Flags &f) {
    return f.res >> 31;
}
""",
        """uint32_t flag_sf(const Flags &f) {
    return f.op == CMP8 ? ((f.res >> 7) & 1u) : (f.res >> 31);
}
""",
        "f.op == CMP8 ?",
    )

    text = replace_once(
        text,
        """    case SUB:
    case CMP:
        return f.a < f.b;
""",
        """    case SUB:
    case CMP:
    case CMP8:
        return f.a < f.b;
""",
        "    case CMP8:\n        return f.a < f.b;",
    )

    text = replace_once(
        text,
        """    case SUB:
    case CMP:
        return ((f.a ^ f.b) & (f.a ^ f.res)) >> 31;
""",
        """    case SUB:
    case CMP:
        return ((f.a ^ f.b) & (f.a ^ f.res)) >> 31;
    case CMP8:
        return (((f.a ^ f.b) & (f.a ^ f.res)) >> 7) & 1u;
""",
        "    case CMP8:\n        return (((f.a ^ f.b)",
    )

    text = replace_once(
        text,
        """    case ADD:
    case SUB:
    case CMP:
        return ((f.a ^ f.b ^ f.res) >> 4) & 1;
""",
        """    case ADD:
    case SUB:
    case CMP:
    case CMP8:
        return ((f.a ^ f.b ^ f.res) >> 4) & 1;
""",
        "    case CMP8:\n        return ((f.a ^ f.b ^ f.res)",
    )

    text = replace_once(
        text,
        """        case CMP: { // SUB without the store
            uint32_t a = load(c, in.dst), b = load(c, in.src);
            f = Flags{CMP, a, b, a - b, 0, 0};
            break;
        }
""",
        """        case CMP: { // SUB without the store
            uint32_t a = load(c, in.dst), b = load(c, in.src);
            f = Flags{CMP, a, b, a - b, 0, 0};
            break;
        }
        case CMP8: {
            uint32_t a = load8(c, in.dst), b = load8(c, in.src);
            f = Flags{CMP8, a, b, (a - b) & 0xffu, 0, 0};
            break;
        }
""",
        "        case CMP8: {",
    )

    INTERP.write_text(text)
    print("Applied Reflex-reached CMP8 and absolute MOV support to pinned fallback interpreter")


if __name__ == "__main__":
    main()
