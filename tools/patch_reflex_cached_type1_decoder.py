#!/usr/bin/env python3
"""Trace the nested MXTables decoder called at guest 004f0199.

Fast run #38205477133 reached 004f0199 (CALL 004eefa0), but not the
return at 004f019e. Follow real translated guest PCs in this callee,
scoped to the blocked single-entry resource by the existing host TLS flag.

This probe observes only; it does not touch any guest register, memory,
stack, status, return address, or readiness state.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-mxtables-inner-v1"
FLAG = "reflex_type1_callback_trace_enabled"
FIRST = 0x004EEFA0
LAST = 0x004EF3FF
RETURN = "004f019e"
REQUIRED = {"004eefa0", RETURN}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* "
    r"(004e(?:ef|f0|f1|f2|f3)[0-9a-f]{2}|004f019e)\b)[^\n]*$"
)


def patch_inner_decoder(generated: Path) -> tuple[list[Path], list[str]]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"No translated chunks found: {generated}")

    found = Counter()
    selected: list[tuple[Path, str, list[str]]] = []
    for path in chunks:
        source = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(source)
                if FIRST <= int(m.group(2), 16) <= LAST or
                m.group(2) == RETURN]
        if hits or MARKER in source:
            selected.append((path, source, hits))
            found.update(hits)

    if not REQUIRED.issubset(found) or any(n != 1 for n in found.values()):
        raise RuntimeError(f"Missing or duplicate decoder guest PCs: {dict(found)}")

    pending: list[tuple[Path, str]] = []
    for path, source, hits in selected:
        if MARKER in source:
            if source.count("/* " + MARKER + " at ") != len(hits):
                raise RuntimeError(f"Partially installed decoder trace in {path.name}")
            continue

        def instrument(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            if pc != RETURN and not FIRST <= int(pc, 16) <= LAST:
                return m.group(0)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    if ({FLAG}) {{
{indent}        static unsigned long long hits = 0u;
{indent}        const unsigned long long n =
{indent}            __atomic_add_fetch(&hits, 1u, __ATOMIC_RELAXED);
{indent}        if (n <= 12u || (n & (n - 1u)) == 0u) {{
{indent}            const uint32_t esp = c->r[4];
{indent}            const int valid = esp >= 0x10000u &&
{indent}                (uint64_t)esp + 12u <= GUEST_SIZE;
{indent}            fprintf(stderr,
{indent}                    "[reflex-mxtables-inner] pc={pc} hit=%llu "
{indent}                    "eax=%08x ebx=%08x ecx=%08x edx=%08x "
{indent}                    "esi=%08x edi=%08x ebp=%08x esp=%08x "
{indent}                    "sp0=%08x sp4=%08x\\n",
{indent}                    (unsigned long long)n, c->r[0], c->r[3],
{indent}                    c->r[1], c->r[2], c->r[6], c->r[7],
{indent}                    c->r[5], esp,
{indent}                    valid ? rd32(esp) : 0xffffffffu,
{indent}                    valid ? rd32(esp + 4u) : 0xffffffffu);
{indent}        }}
{indent}    }}
{indent}}}
''' + m.group(0)

        replacement = PATTERN.sub(instrument, source)
        if "#include <stdio.h>" not in replacement:
            replacement = "#include <stdio.h>\n" + replacement
        if ("extern __thread unsigned int " + FLAG + ";") not in replacement and \
                ("__thread unsigned int " + FLAG + " = 0u;") not in replacement:
            replacement = "extern __thread unsigned int " + FLAG + ";\n" + replacement
        pending.append((path, replacement))

    # Validate the whole translation before modifying any chunk.
    for path, replacement in pending:
        path.write_text(replacement)
    return [path for path, _, _ in selected], sorted(found)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--generated", type=Path, default=GENERATED)
    args = p.parse_args()
    files, pcs = patch_inner_decoder(args.generated)
    print(f"Tracked nested MXTables decoder ({len(pcs)} actual guest PCs, "
          f"{len(files)} generated chunks)")


if __name__ == "__main__":
    main()
