#!/usr/bin/env python3
"""Bounded read-only diagnostic for Reflex resource queue worker.

The original 0084c760 worker consumes queued requests from +0xec/+0xf0/+0xf4,
and readiness writers at 0084bfb8 and 0084b698 can update a record's +0x94
status field. This is a companion to the consumer's 0084a7f0 ready poll.
It changes no game registers, memory, events, thread state or assets.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-resource-worker-v1"
WORKER = (
    "0084c7f6",  # read-index versus write-index (queue empty?)
    "0084c823",  # request kind dispatch
    "0084c8d0",  # resource lookup absent
    "0084c988",  # next resource branch
    "0084ca40",  # status-zero gate
    "0084cb91",  # queue request processed
    "0084cbfe",  # no queued request
)
WRITERS = ("0084bfb8", "0084b698")
SITES = WORKER + WRITERS
REQUIRED = {"0084c7f6", "0084c823"}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (" +
    "|".join(SITES) + r")\b)[^\n]*$"
)


def patch_worker(generated: Path) -> list[Path]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    found = []
    relevant = []
    for path in chunks:
        source = path.read_text()
        sites = [m.group(2) for m in PATTERN.finditer(source)]
        if not sites and MARKER not in source:
            continue
        if MARKER in source:
            if source.count(MARKER) != len(sites) or \
                    source.count("[reflex-resource-worker]") != len(sites):
                raise RuntimeError(f"Incomplete previous worker tracing in {path.name}")
        found.extend(sites)
        relevant.append((path, source, bool(MARKER in source)))
    counts = Counter(found)
    if not REQUIRED.issubset(counts) or any(n != 1 for n in counts.values()):
        raise RuntimeError(
            f"Expected unique worker checkpoints {sorted(REQUIRED)}, got {dict(counts)}")

    modifications = []
    for path, source, existing in relevant:
        if existing:
            continue

        def trace(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            # The two writer sites use different register conventions.
            # Do not infer an object from them; print CPU values alone.
            worker = pc in WORKER
            extra = ""
            if worker:
                extra = f'''{indent}        const uint32_t manager = c->r[3];
{indent}        const int readable = manager >= 0x10000u &&
{indent}            (uint64_t)manager + 0xf8u <= GUEST_SIZE;
{indent}        const uint32_t consumed = readable ? rd32(manager + 0xecu) : 0u;
{indent}        const uint32_t write_snapshot = readable ? rd32(manager + 0xf0u) : 0u;
{indent}        const uint32_t writer = readable ? rd32(manager + 0xf4u) : 0u;
{indent}        uint32_t kind = 0xffffffffu;
{indent}        const uint64_t record = (uint64_t)manager + 0x104u +
{indent}            (uint64_t)consumed * 0x194u;
{indent}        if (readable && consumed < 1024u &&
{indent}            record >= 0x10000u && record + 4u <= GUEST_SIZE)
{indent}            kind = rd32((uint32_t)record);
'''
                # Keep integer values distinct: 0xffffffff = no valid record.
            else:
                extra = f'''{indent}        const uint32_t manager = 0u;
{indent}        const uint32_t consumed = 0u;
{indent}        const uint32_t write_snapshot = 0u;
{indent}        const uint32_t writer = 0u;
{indent}        const uint32_t kind = 0xffffffffu;
'''
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long count = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&count, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{extra}{indent}        fprintf(stderr,
{indent}                "[reflex-resource-worker] pc={pc} n=%llu "
{indent}                "manager=%08x read=%u snapshot=%u write=%u kind=%08x "
{indent}                "eax=%08x ecx=%08x esi=%08x\\n",
{indent}                (unsigned long long)n, manager,
{indent}                consumed, write_snapshot, writer, kind,
{indent}                c->r[0], c->r[1], c->r[6]);
{indent}    }}
{indent}}}
''' + m.group(0)

        patched = PATTERN.sub(trace, source)
        if "#include <stdio.h>" not in patched:
            patched = "#include <stdio.h>\n" + patched
        modifications.append((path, patched))
    # Commit only after verifying all required sites/uniqueness.
    for path, patched in modifications:
        path.write_text(patched)
    return [path for path, _, _ in relevant]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    paths = patch_worker(args.generated)
    print(f"Installed resource worker queue trace in {len(paths)} chunk(s)")


if __name__ == "__main__":
    main()
