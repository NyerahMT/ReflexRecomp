#!/usr/bin/env python3
"""Patch the pinned recomp-kit SEH dispatcher for Reflex bring-up."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "kit/runtime/seh.cpp"
s = p.read_text()
old = '''    if (disposition == 0) {
        LOGW("ExceptionContinueExecution requested; not supported (record=%08x code=%08x "
             "registration=%08x handler=%08x)\\n",
             d->record, rd32(d->record), reg, handler);
        fatal_abort();
    }
'''
# Pinned kit currently omits the newline in this literal; accept that exact form too.
if old not in s:
    old = '''    if (disposition == 0) {
        LOGW("ExceptionContinueExecution requested; not supported (record=%08x code=%08x "
             "registration=%08x handler=%08x)",
             d->record, rd32(d->record), reg, handler);
        fatal_abort();
    }
'''
new = '''    if (disposition == 0) {
        // ExceptionContinueExecution is valid for a continuable exception. Restore
        // the guest integer/control CONTEXT because a filter may have edited it.
        if (rd32(d->record + 4) & 1u) { // EXCEPTION_NONCONTINUABLE
            LOGW("SEH: attempted continuation of noncontinuable exception "
                 "(record=%08x code=%08x registration=%08x handler=%08x)",
                 d->record, rd32(d->record), reg, handler);
            fatal_abort();
        }
        const int regs[] = {R_EDI, R_ESI, R_EBX, R_EDX, R_ECX, R_EAX, R_EBP};
        for (uint32_t i = 0; i < 7; ++i)
            c->r[regs[i]] = rd32(d->context + 0x9c + i * 4);
        c->eip = rd32(d->context + 0xb8);
        x86_set_eflags(c, rd32(d->context + 0xc0));
        c->r[R_ESP] = rd32(d->context + 0xc4);
        LOGV("SEH continue execution: record=%08x code=%08x EIP=%08x ESP=%08x",
             d->record, rd32(d->record), c->eip, c->r[R_ESP]);
        return disposition;
    }
'''
if old not in s:
    raise SystemExit("seh.cpp continuation block no longer matches pinned recomp-kit")
p.write_text(s.replace(old, new, 1))
print("Patched recomp-kit SEH ExceptionContinueExecution support")
