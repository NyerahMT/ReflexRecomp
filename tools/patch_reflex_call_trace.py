#!/usr/bin/env python3
"""Instrument the cached generated dispatch for the current Reflex frontier."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "build" / "recomp" / "gen" / "table.c"
MARKER = "reflex caller trace 008244c0:"
ANCHOR = """void recomp_call(X86 *c, uint32_t target)
{
"""

def main():
    if not TABLE.is_file():
        raise SystemExit(f"missing cached generated table: {TABLE}")
    text = TABLE.read_text()
    if MARKER in text:
        print("Reflex caller trace already present")
        return
    if text.count(ANCHOR) != 1:
        raise SystemExit("expected exactly one recomp_call anchor")
    trace = ANCHOR + """    if (target == 0x008244c0u) {
        const uint32_t esp = c->r[R_ESP];
        const uint32_t ret = rd32(esp);
        const uint32_t arg0 = rd32(esp + 4);
        fprintf(stderr,
                "[recomp] reflex caller trace 008244c0: ret=%08x esp=%08x ecx=%08x "
                "arg0=%08x eax=%08x edx=%08x esi=%08x edi=%08x\\n",
                ret, esp, c->r[R_ECX], arg0, c->r[R_EAX], c->r[R_EDX],
                c->r[R_ESI], c->r[R_EDI]);
    }
"""
    TABLE.write_text(text.replace(ANCHOR, trace, 1))
    print("Instrumented cached dispatch for Registry::FUN_008244c0 caller trace")

if __name__ == "__main__":
    main()
