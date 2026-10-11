#!/usr/bin/env python3
"""Diagnose original guest instructions after MXTables_Default type-1 setup.

Fast probe #38184374941 reached 0084be11 for MXTables_Default.dx9.package
(resource count 1), but not 0084be40 or the completion write 0084bfb8.
Trace each existing translated instruction in [0084be11, 0084be40]
without changing guest registers, memory, branch outcomes, or readiness.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-type1-gap-v1"
FIRST = int("0084be11", 16)
LAST = int("0084be40", 16)
# Match only a generated instruction comment, not the other diagnostic probes.
PATTERN = re.compile(r"(?m)^([ \t]*)(?=[^\n]*/\* (0084be[0-9a-f]{2})\b)[^\n]*$")


def patch_type1_gap(generated: Path) -> tuple[list[Path], list[str]]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"Cached translation chunks missing in {generated}")
    found = []
    edits = []
    for path in chunks:
        source = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(source)
                if FIRST <= int(m.group(2), 16) <= LAST]
        if not hits and MARKER not in source:
            continue
        installed = MARKER in source
        if installed and (source.count(MARKER) != len(hits) or
                          source.count("[reflex-type1-gap]") != len(hits)):
            raise RuntimeError(f"Partial existing type-1 gap probe in {path.name}")
        found.extend(hits)
        edits.append((path, source, installed))

    counts = Counter(found)
    if (not {"0084be11", "0084be40"}.issubset(counts) or
            any(count != 1 for count in counts.values())):
        raise RuntimeError(f"Missing/duplicate type-1 gap sites: {dict(counts)}")

    pending = []
    for path, source, installed in edits:
        if installed:
            continue

        def instrument(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            if not FIRST <= int(pc, 16) <= LAST:
                return m.group(0)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long calls = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&calls, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}        const uint32_t sp = c->r[4];
{indent}        const int valid_sp = sp >= 0x10000u &&
{indent}            (uint64_t)sp + 8u <= GUEST_SIZE;
{indent}        fprintf(stderr, "[reflex-type1-gap] pc={pc} n=%llu "
{indent}                "eax=%08x ebx=%08x ecx=%08x edx=%08x "
{indent}                "esi=%08x edi=%08x ebp=%08x esp=%08x "
{indent}                "sp0=%08x sp4=%08x\\n",
{indent}                (unsigned long long)n,
{indent}                c->r[0], c->r[3], c->r[1], c->r[2],
{indent}                c->r[6], c->r[7], c->r[5], sp,
{indent}                valid_sp ? rd32(sp) : 0xffffffffu,
{indent}                valid_sp ? rd32(sp + 4u) : 0xffffffffu);
{indent}    }}
{indent}}}
''' + m.group(0)

        replacement = PATTERN.sub(instrument, source)
        if '#include <stdio.h>' not in replacement:
            replacement = '#include <stdio.h>\n' + replacement
        pending.append((path, replacement))

    # Preflight ALL PC anchors before touching even one generated C file.
    for path, replacement in pending:
        path.write_text(replacement)
    return [p for p, _, _ in edits], sorted(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--generated', type=Path, default=GENERATED)
    args = parser.parse_args()
    paths, pcs = patch_type1_gap(args.generated)
    print(f"Installed type-1 setup-gap probe ({len(pcs)} original PCs, "
          f"{len(paths)} chunks): {', '.join(pcs)}")


if __name__ == '__main__':
    main()
