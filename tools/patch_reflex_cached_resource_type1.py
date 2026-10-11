#!/usr/bin/env python3
"""Trace the eighth (type-1) Reflex resource request's internal processing.

Real runtime after ready-poll instrumentation:
- first seven worker requests reach 0084cb91 cleanup,
- eighth request (queue index 7, kind 1) reaches dispatch 0084c823,
- worker does NOT reach 0084cb91 for this request in the 15-second gate,
- the waiting loader's resource object is found but readiness remains 0.

Original type-1 branch 0084caa3:
indirect resource lookup -> null/status guards -> prepare -> 0084bc70 process.
This script only traces translated instruction boundaries and guest state.
No resource or guest state is modified.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-type1-resource-v1"
SITES = (
    "0084caa3",  # type-1 handler starts
    "0084cad9",  # object lookup virtual call
    "0084cae3",  # null object branch
    "0084cb2d",  # resource status readiness test
    "0084cb34",  # branch if not ready
    "0084cb49",  # prepare resource processing
    "0084cb79",  # 0084bc70 processing call
    "0084cb7e",  # return from processing call
)
REQUIRED = {"0084caa3", "0084cad9", "0084cb79", "0084cb7e"}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (" + "|".join(SITES) +
    r")\b)[^\n]*$"
)


def patch_type1(generated: Path) -> list[Path]:
    files = sorted(generated.glob("chunk_*.c"))
    if not files:
        raise RuntimeError("No cached translated chunks")
    matches = []
    found = []
    for path in files:
        source = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(source)]
        if not hits and MARKER not in source:
            continue
        if MARKER in source:
            if source.count(MARKER) != len(hits) or \
                    source.count("[reflex-type1-resource]") != len(hits):
                raise RuntimeError(f"Partial previously installed trace: {path.name}")
        matches.append((path, source, MARKER in source))
        found.extend(hits)
    count = Counter(found)
    if not REQUIRED.issubset(count) or any(v != 1 for v in count.values()):
        raise RuntimeError(
            f"Missing/duplicate type-1 checkpoints: {dict(count)}")
    replacements = []
    for path, source, existing in matches:
        if existing:
            continue

        def probe(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long n_calls = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&n_calls, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}        const uint32_t manager = c->r[3];
{indent}        const uint32_t resource = c->r[6];
{indent}        const int manager_ok = manager >= 0x10000u &&
{indent}            (uint64_t)manager + 0xf0u <= GUEST_SIZE;
{indent}        const int resource_ok = resource >= 0x10000u &&
{indent}            (uint64_t)resource + 0x98u <= GUEST_SIZE;
{indent}        const uint32_t index = manager_ok ? rd32(manager + 0xecu) : 0u;
{indent}        const uint32_t status = resource_ok ? rd32(resource + 0x94u) : 0xffffffffu;
{indent}        fprintf(stderr,
{indent}                "[reflex-type1-resource] pc={pc} n=%llu "
{indent}                "manager=%08x index=%u object=%08x status=%08x "
{indent}                "eax=%08x ecx=%08x edx=%08x edi=%08x\\n",
{indent}                (unsigned long long)n, manager, index, resource, status,
{indent}                c->r[0], c->r[1], c->r[2], c->r[7]);
{indent}    }}
{indent}}}
''' + m.group(0)

        result = PATTERN.sub(probe, source)
        if "#include <stdio.h>" not in result:
            result = "#include <stdio.h>\n" + result
        replacements.append((path, result))

    # Verify every required source location before any writes to private input.
    for path, result in replacements:
        path.write_text(result)
    return [path for path, _, _ in matches]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    patched = patch_type1(args.generated)
    print(f"Traced resource type-1 handler in {len(patched)} chunks")


if __name__ == "__main__":
    main()
