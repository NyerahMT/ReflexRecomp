#!/usr/bin/env python3
"""Track original single-entry Reflex package loads without global sampling bias.

The older per-instruction probes log the first eight executions and powers of
two globally. By the time MXTables_Default runs, those early samples are gone.
Observe only the genuine guest type-1 objects with one resource and base zero.
No translated jump, loading status, memory, or guest register is changed.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-type1-single-v1"
FIRST = int("0084be40", 16)
LAST = int("0084bfb8", 16)
REQUIRED = {"0084be40", "0084be5d", "0084beed",
            "0084bf12", "0084bf49", "0084bfb8"}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (0084b[ef][0-9a-f]{2})\b)[^\n]*$"
)


def patch_single_entry(generated: Path) -> tuple[list[Path], list[str]]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"Cached translation chunks missing: {generated}")
    found: list[str] = []
    sources: list[tuple[Path, str, bool]] = []
    for path in chunks:
        source = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(source)
                if FIRST <= int(m.group(2), 16) <= LAST]
        installed = MARKER in source
        if installed and (source.count(MARKER) != len(hits) or
                          source.count("[reflex-type1-single]") != len(hits)):
            raise RuntimeError(f"Partial installed single-entry probe: {path.name}")
        if hits or installed:
            found.extend(hits)
            sources.append((path, source, installed))
    counts = Counter(found)
    if not REQUIRED.issubset(counts) or any(value != 1 for value in counts.values()):
        raise RuntimeError(f"Missing/duplicate single-entry PCs: {dict(counts)}")

    pending: list[tuple[Path, str]] = []
    for path, source, installed in sources:
        if installed:
            continue

        def inject(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            if not FIRST <= int(pc, 16) <= LAST:
                return m.group(0)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long single_hits = 0u;
{indent}    const uint32_t obj = c->r[3];
{indent}    if (obj >= 0x10000u &&
{indent}        (uint64_t)obj + 0x98u <= GUEST_SIZE &&
{indent}        rd32(obj + 0x84u) == 1u &&
{indent}        rd32(obj + 0x90u) == 0u) {{
{indent}        const unsigned long long n =
{indent}            __atomic_add_fetch(&single_hits, 1u, __ATOMIC_RELAXED);
{indent}        if (n <= 12u || (n & (n - 1u)) == 0u) {{
{indent}            fprintf(stderr,
{indent}                    "[reflex-type1-single] pc={pc} hit=%llu "
{indent}                    "obj=%08x status=%08x list=%08x "
{indent}                    "eax=%08x ecx=%08x edx=%08x "
{indent}                    "esi=%08x edi=%08x esp=%08x\\n",
{indent}                    (unsigned long long)n, obj,
{indent}                    rd32(obj + 0x94u), rd32(obj + 0x80u),
{indent}                    c->r[0], c->r[1], c->r[2],
{indent}                    c->r[6], c->r[7], c->r[4]);
{indent}        }}
{indent}    }}
{indent}}}
''' + m.group(0)

        replacement = PATTERN.sub(inject, source)
        if "#include <stdio.h>" not in replacement:
            replacement = "#include <stdio.h>\n" + replacement
        pending.append((path, replacement))
    # Transactional preflight above means never leave partly patched chunks.
    for path, replacement in pending:
        path.write_text(replacement)
    return [path for path, _, _ in sources], sorted(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    paths, pcs = patch_single_entry(args.generated)
    print(f"Installed one-resource loader probe ({len(pcs)} guest PCs, "
          f"{len(paths)} chunks)")


if __name__ == "__main__":
    main()
