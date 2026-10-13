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

    // Observe post-loader indirect calls in the FMOD audio worker. Read-only tracing; never skip a guest call.
    if (trace_ret == 0x008065b9u || trace_ret == 0x008067fdu ||
        trace_ret == 0x0080fc3cu) {
        const int stack_ok = trace_esp >= 0x10000u &&
            (uint64_t)trace_esp + 16u <= GUEST_SIZE;
        fprintf(stderr,
                "[reflex-worker-null] ret=%08x target=%08x esp=%08x "
                "eax=%08x ebx=%08x ecx=%08x edx=%08x esi=%08x edi=%08x "
                "arg0=%08x arg1=%08x arg2=%08x\\n",
                trace_ret, target, trace_esp,
                c->r[R_EAX], c->r[R_EBX], c->r[R_ECX], c->r[R_EDX],
                c->r[R_ESI], c->r[R_EDI],
                stack_ok ? rd32(trace_esp + 4u) : 0xffffffffu,
                stack_ok ? rd32(trace_esp + 8u) : 0xffffffffu,
                stack_ok ? rd32(trace_esp + 12u) : 0xffffffffu);
        const int reg_ids[] = {R_EAX, R_EBX, R_ECX, R_EDX, R_ESI, R_EDI};
        const char *reg_names[] = {"eax", "ebx", "ecx", "edx", "esi", "edi"};
        for (int i = 0; i < 6; ++i) {
            const uint32_t p = c->r[reg_ids[i]];
            const int valid = p >= 0x10000u && (uint64_t)p + 16u <= GUEST_SIZE;
            fprintf(stderr,
                    "[reflex-worker-null] reg=%s ptr=%08x valid=%d "
                    "w0=%08x w1=%08x w2=%08x w3=%08x\\n",
                    reg_names[i], p, valid,
                    valid ? rd32(p) : 0xffffffffu,
                    valid ? rd32(p + 4u) : 0xffffffffu,
                    valid ? rd32(p + 8u) : 0xffffffffu,
                    valid ? rd32(p + 12u) : 0xffffffffu);
        }
    }

    // reflex-finalizer-vcall-v1: distinguish the two indirect resource
    // finalizer lookups from the early exits in original 00543cd0.
    // 00543d68: resource availability query; 00543d86: resource-load call.
    // These addresses are guest return sites, not host function pointers.
    if (trace_ret == 0x00543d68u || trace_ret == 0x00543d86u) {
        static uint64_t query_calls = 0u;
        static uint64_t load_calls = 0u;
        const int is_load = trace_ret == 0x00543d86u;
        uint64_t n = is_load
            ? __atomic_add_fetch(&load_calls, 1u, __ATOMIC_RELAXED)
            : __atomic_add_fetch(&query_calls, 1u, __ATOMIC_RELAXED);
        if (n <= 16u || (n & (n - 1u)) == 0u) {
            const int valid_stack = trace_esp >= 0x10000u
                && (uint64_t)trace_esp + 12u <= GUEST_SIZE;
            fprintf(stderr,
                    "[reflex-finalizer-call] phase=%s n=%llu site=%08x "
                    "target=%08x this=%08x arg0=%08x arg1=%08x\\n",
                    is_load ? "load" : "query",
                    (unsigned long long)n, trace_ret, target,
                    c->r[R_ECX],
                    valid_stack ? rd32(trace_esp + 4u) : 0u,
                    valid_stack ? rd32(trace_esp + 8u) : 0u);
        }
    }

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

    if (target == 0x0084c190u) {
        // Trace the resource-task *submission* rather than the lookup spin.
        // Args: manager, request type, key, secondary key, ... as seen
        // at 0084a80b. Retained as raw guest values to avoid interpreting
        // arbitrary pointers as a safe nul-terminated host string.
        static uint64_t reflex_resource_enqueue_calls = 0;
        const uint64_t q_n =
            __atomic_add_fetch(&reflex_resource_enqueue_calls, 1, __ATOMIC_RELAXED);
        if (q_n <= 32 || (q_n & (q_n - 1)) == 0) {
            const uint32_t manager = (trace_esp >= 0x10000u && trace_esp <= GUEST_SIZE - 32u)
                ? rd32(trace_esp + 4) : 0u;
            const uint32_t first_key = (trace_esp >= 0x10000u && trace_esp <= GUEST_SIZE - 16u)
                ? rd32(trace_esp + 12) : 0u;
            const uint32_t key_prefix = first_key &&
                (first_key >= 0x10000u && first_key <= GUEST_SIZE - 4u) ? rd32(first_key) : 0u;
            const uint32_t event = manager &&
                (manager >= 0x10000u && manager <= GUEST_SIZE - 0xfcu) ?
                rd32(manager + 0xf8u) : 0u;
            fprintf(stderr,
                    "[reflex-queue] call=%llu ret=%08x manager=%08x "
                    "type=%08x key=%08x prefix=%08x arg3=%08x "
                    "event=%08x\\n",
                    (unsigned long long)q_n, trace_ret, manager,
                    rd32(trace_esp + 8), first_key, key_prefix,
                    rd32(trace_esp + 16), event);
        }
    }

    if (target == 0x0084a890u) {
        // This virtual resource lookup searches UI data by key. Direct
        // cross-references cannot identify its callers; sample the guest
        // return site and two x86 stack arguments on power-of-two calls.
        static uint64_t reflex_ui_lookup_calls = 0;
        const uint64_t ui_n =
            __atomic_add_fetch(&reflex_ui_lookup_calls, 1, __ATOMIC_RELAXED);
        if ((ui_n & (ui_n - 1)) == 0) {
            // Guest field [ECX+0x62b54] is a 24-byte critical section,
            // NOT a language string. Read its lock-count member safely.
            // Locale text is separately traced in crt_fgets(language.txt).
            const uint64_t lock_addr64 =
                (uint64_t)c->r[R_ECX] + 0x62b58u;
            const uint32_t lock_count =
                lock_addr64 >= 0x10000u &&
                lock_addr64 + 4u <= GUEST_SIZE
                ? rd32((uint32_t)lock_addr64) : 0u;
            // Function 008814a0 writes the parsed language-file enum
            // to this guest global at 0088178d or clears it at 00881794.
            const uint32_t locale_id = rd32(0x00a94078u);
            fprintf(stderr,
                    "[reflex-ui-lookup] call=%llu ret=%08x this=%08x "
                    "arg0=%08x arg1=%08x eax=%08x esi=%08x edi=%08x "
                    "lock_count=%08x locale_id=%08x\\n",
                    (unsigned long long)ui_n, trace_ret, c->r[R_ECX],
                    rd32(trace_esp + 4), rd32(trace_esp + 8),
                    c->r[R_EAX], c->r[R_ESI], c->r[R_EDI],
                    lock_count, locale_id);
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
