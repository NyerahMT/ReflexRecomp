#!/usr/bin/env python3
"""Instrument cached generated dispatch for the active Reflex runtime frontier."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "build" / "recomp" / "gen" / "table.c"
MARKER = "reflex frontier trace v2:"
ANCHOR = """void recomp_call(X86 *c, uint32_t target)
{
"""

def main():
    if not TABLE.is_file():
        raise SystemExit(f"missing cached generated table: {TABLE}")
    text = TABLE.read_text()
    if MARKER in text:
        print("Reflex frontier trace v2 already present")
        return
    if text.count(ANCHOR) != 1:
        raise SystemExit("expected exactly one recomp_call anchor")

    trace = ANCHOR + """    const uint32_t trace_esp = c->r[R_ESP];
    const uint32_t trace_ret = rd32(trace_esp);

    if (trace_ret == 0x007add47u) {
        fprintf(stderr,
                "[recomp] reflex producer trace 007add45: target=%08x esp=%08x ecx=%08x "
                "a0=%08x a1=%08x a2=%08x eax=%08x edx=%08x esi=%08x edi=%08x\\n",
                target, trace_esp, c->r[R_ECX], rd32(trace_esp + 4), rd32(trace_esp + 8),
                rd32(trace_esp + 12), c->r[R_EAX], c->r[R_EDX], c->r[R_ESI], c->r[R_EDI]);
    }

    if (target == 0x008244c0u) {
        const uint32_t arg0 = rd32(trace_esp + 4);
        fprintf(stderr,
                "[recomp] reflex caller trace 008244c0: ret=%08x esp=%08x ecx=%08x "
                "arg0=%08x eax=%08x edx=%08x esi=%08x edi=%08x\\n",
                trace_ret, trace_esp, c->r[R_ECX], arg0, c->r[R_EAX], c->r[R_EDX],
                c->r[R_ESI], c->r[R_EDI]);
    }

    if (target == 0x005c3380u || target == 0x005c33c0u) {
        fprintf(stderr,
                "[recomp] reflex frontier trace v2: hash target=%08x ret=%08x esp=%08x "
                "eax=%08x ecx=%08x edx=%08x esi=%08x edi=%08x\\n",
                target, trace_ret, trace_esp, c->r[R_EAX], c->r[R_ECX], c->r[R_EDX],
                c->r[R_ESI], c->r[R_EDI]);
    }

    if (trace_ret == 0x0084df6au) {
        fprintf(stderr,
                "[recomp] reflex frontier trace v2: allocator indirect target=%08x ret=%08x "
                "esp=%08x eax=%08x ebx=%08x ecx=%08x edx=%08x esi=%08x edi=%08x\\n",
                target, trace_ret, trace_esp, c->r[R_EAX], c->r[R_EBX], c->r[R_ECX],
                c->r[R_EDX], c->r[R_ESI], c->r[R_EDI]);
    }

    if (target == 0x0084a890u) {
        // This virtual resource lookup searches UI data by key. Direct
        // cross-references cannot identify its callers; sample the guest
        // return site and two x86 stack arguments on power-of-two calls.
        static uint64_t reflex_ui_lookup_calls = 0;
        const uint64_t ui_n =
            __atomic_add_fetch(&reflex_ui_lookup_calls, 1, __ATOMIC_RELAXED);
        if ((ui_n & (ui_n - 1)) == 0) {
            fprintf(stderr,
                    "[reflex-ui-lookup] call=%llu ret=%08x this=%08x "
                    "arg0=%08x arg1=%08x eax=%08x esi=%08x edi=%08x\\n",
                    (unsigned long long)ui_n, trace_ret, c->r[R_ECX],
                    rd32(trace_esp + 4), rd32(trace_esp + 8),
                    c->r[R_EAX], c->r[R_ESI], c->r[R_EDI]);
        }
    }

    if (target == 0x008fa06au) {
        fprintf(stderr,
                "[recomp] reflex frontier trace v2: memset thunk ret=%08x esp=%08x "
                "dst=%08x value=%08x size=%08x eax=%08x\\n",
                trace_ret, trace_esp, rd32(trace_esp + 4), rd32(trace_esp + 8),
                rd32(trace_esp + 12), c->r[R_EAX]);
    }
"""

    TABLE.write_text(text.replace(ANCHOR, trace, 1))
    print("Instrumented cached dispatch for Reflex hash/allocator frontier traces")

if __name__ == "__main__":
    main()
