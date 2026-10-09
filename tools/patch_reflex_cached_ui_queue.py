#!/usr/bin/env python3
"""Trace Reflex's direct-call resource request path in cached translations.

CALL_FN(0084c190) calls generated C directly, bypassing recomp_call().
Instrument the real generated body_0084c190 entry (entry_=0), rather than
misinterpreting an absent recomp_call trace as an absent guest request.
Only the private cached translation is modified; game assets stay untouched.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build" / "recomp" / "gen"
ANCHOR = re.compile(
    r"(?m)^([ \t]*)static void body_0084c190\(X86 \*c, uint32_t entry_\) \{\n"
)
MARKER = "reflex-ui-direct-queue-v1"
TRACE = r"""
    /* reflex-ui-direct-queue-v1: guest 0084c190 is called with CALL_FN. */
    if (entry_ == 0u) {
        static uint64_t n_requests = 0u;
        const uint64_t count =
            __atomic_add_fetch(&n_requests, 1u, __ATOMIC_RELAXED);
        if (count <= 32u || (count & (count - 1u)) == 0u) {
            const uint32_t sp = c->r[4];
            uint32_t args[8] = {0};
            if (sp >= 0x10000u && sp <= GUEST_SIZE - 36u) {
                for (unsigned i = 0; i < 8u; ++i)
                    args[i] = rd32(sp + 4u + 4u * i);
            }
            const uint32_t manager = args[0];
            const uint32_t manager_event =
                manager >= 0x10000u && manager <= GUEST_SIZE - 0xfcu
                ? rd32(manager + 0xf8u) : 0u;
            fprintf(stderr,
                    "[reflex-direct-queue] n=%llu ret=%08x this=%08x "
                    "type=%08x a2=%08x a3=%08x a4=%08x a5=%08x a6=%08x "
                    "event=%08x\\n",
                    (unsigned long long)count,
                    sp >= 0x10000u && sp <= GUEST_SIZE - 4u ? rd32(sp) : 0u,
                    args[0], args[1], args[2], args[3],
                    args[4], args[5], args[6], manager_event);
        }
    }
"""


def patch_queue(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"No cached translation chunks under {generated}")
    found = []
    for file in chunks:
        source = file.read_text()
        count = len(ANCHOR.findall(source))
        if count or MARKER in source:
            found.append((file, source, count))
    if len(found) != 1:
        raise RuntimeError(f"Expected one queue translation, found {len(found)}")
    file, source, count = found[0]
    if MARKER in source:
        if count != 1 or source.count(MARKER) != 1:
            raise RuntimeError("Malformed duplicate queue instrumentation")
        return file
    if count != 1:
        raise RuntimeError("Queue translation body anchor missing")
    source = ANCHOR.sub(lambda m: m.group(0) + TRACE, source, count=1)
    if "#include <stdio.h>" not in source:
        source = "#include <stdio.h>\n" + source
    file.write_text(source)
    return file


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--generated", type=Path, default=GENERATED)
    args = p.parse_args()
    target = patch_queue(args.generated)
    print(f"Traced direct CALL_FN resource submission in {target.name}")


if __name__ == "__main__":
    main()
