#!/usr/bin/env python3
"""Trace the real MXUI resource-processing call which stalls Reflex LOADING.

Runtime #38183166071 reached worker 0084cb79 (CALL 0084bc70) for
type-1 request index 7, object 023c04c4, and never reached 0084cb7e.
Earlier type-1 calls returned and transitioned resource status 0 -> 1.

Original game's code in 0084bc70 does:
  lock/lookup -> resource metadata parsing -> package iteration ->
  callback/read -> status=1 at 0084bfb8.
This patch observes original translated instruction boundaries. It never
marks a resource ready, changes guest state, or bypasses loading.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-type1-body-v1"
# Verified against the user's original PE32 MXReflex.exe disassembly.
STAGES = (
    "0084bcbc",  # lock resource context
    "0084bccf",  # resource metadata lookup / helper 007fa250
    "0084bce9",  # virtual resource lookup
    "0084bcf4",  # metadata block constructor 00810600
    "0084bd0e",  # CRT string helper
    "0084bd25",  # CRT string helper
    "0084bd5d",  # archive/context lock
    "0084bda3",  # resource block setup 008104d0
    "0084be11",  # number of entries / empty path
    "0084be40",  # start per-entry loop
    "0084be5d",  # per-entry stream read via import 0091637c
    "0084beed",  # per-entry resource virtual callback
    "0084bf10",  # alternate per-entry virtual callback
    "0084bf12",  # per-entry callback has returned
    "0084bf49",  # increment entry counter
    "0084bf72",  # close/deallocate stream
    "0084bf8b",  # close stream via import 00916350
    "0084bfb8",  # write readiness status +0x94 = 1
)
REQUIRED = {"0084bcbc", "0084bccf", "0084bce9", "0084be11",
            "0084be40", "0084bf12", "0084bfb8"}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (" + "|".join(STAGES) +
    r")\b)[^\n]*$"
)


def patch_type1_body(generated: Path) -> list[Path]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"Cached translation chunks missing in {generated}")
    found = []
    edits = []
    for path in chunks:
        source = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(source)]
        if not hits and MARKER not in source:
            continue
        if MARKER in source:
            if source.count(MARKER) != len(hits) or \
                    source.count("[reflex-type1-body]") != len(hits):
                raise RuntimeError(f"Partial existing body probe in {path.name}")
        edits.append((path, source, MARKER in source))
        found.extend(hits)

    counts = Counter(found)
    if not REQUIRED.issubset(counts) or any(v != 1 for v in counts.values()):
        raise RuntimeError(
            f"Missing/duplicate type-1 resource body sites: {dict(counts)}"
        )

    pending = []
    for path, original, installed in edits:
        if installed:
            continue

        def instrument(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long samples = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&samples, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}        const uint32_t obj = c->r[3];
{indent}        const int valid = obj >= 0x10000u &&
{indent}            (uint64_t)obj + 0x98u <= GUEST_SIZE;
{indent}        const uint32_t count = valid ? rd32(obj + 0x84u) : 0xffffffffu;
{indent}        const uint32_t status = valid ? rd32(obj + 0x94u) : 0xffffffffu;
{indent}        const uint32_t list = valid ? rd32(obj + 0x80u) : 0u;
{indent}        const uint32_t file_base = valid ? rd32(obj + 0x90u) : 0u;
{indent}        fprintf(stderr,
{indent}                "[reflex-type1-body] pc={pc} n=%llu obj=%08x "
{indent}                "count=%u status=%08x list=%08x base=%08x "
{indent}                "loop_index=%08x eax=%08x ecx=%08x "
{indent}                "edx=%08x ebp=%08x esp=%08x\\n",
{indent}                (unsigned long long)n, obj, count, status,
{indent}                list, file_base, c->r[6], c->r[0],
{indent}                c->r[1], c->r[2], c->r[5], c->r[4]);
{indent}    }}
{indent}}}
''' + m.group(0)

        replaced = PATTERN.sub(instrument, original)
        if "#include <stdio.h>" not in replaced:
            replaced = "#include <stdio.h>\n" + replaced
        pending.append((path, replaced))

    # Validate all address anchors before touching even one translated file.
    for path, replacement in pending:
        path.write_text(replacement)
    return [path for path, _, _ in edits]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    files = patch_type1_body(args.generated)
    print(f"Installed type-1 body checkpoints ({len(STAGES)} sites, "
          f"{len(files)} translated chunks)")


if __name__ == "__main__":
    main()
