#!/usr/bin/env python3
"""Observe the resource-ready polling loop blocking Reflex loading.

Original game:
  004e6ceb virtual call -> 0084a7f0
  0084a80b queues a resource request through 0084c190
  0084a819 calls resource status virtual method (+0x28)
  0084a81d tests first result; 0084a837 loops on zero after Sleep(1)
  0084a83a is the successful fallthrough

Sample actual guest values without fabricating ready states or signals.
Only generated private translation is changed, never the original game.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-ready-poll-v1"
SITES = ("0084a81d", "0084a837", "0084a83a")
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (" +
    "|".join(SITES) +
    r")\b)[^\n]*$"
)


def patch_ready_poll(generated: Path) -> list[Path]:
    paths = sorted(generated.glob("chunk_*.c"))
    if not paths:
        raise RuntimeError("Missing cached translation")
    matches = []
    found = []
    for path in paths:
        data = path.read_text()
        hits = list(PATTERN.finditer(data))
        if not hits and MARKER not in data:
            continue
        if MARKER in data:
            if data.count(MARKER) != len(hits) or \
                    data.count("[reflex-ready-poll]") != len(hits):
                raise RuntimeError(f"Partial prior patch in {path.name}")
        matches.append((path, data, bool(MARKER in data)))
        found.extend(m.group(2) for m in hits)
    counts = Counter(found)
    if sorted(found) != sorted(SITES) or any(n != 1 for n in counts.values()):
        raise RuntimeError(f"Expected one each of {SITES}; got {dict(counts)}")

    outputs = []
    for path, content, existing in matches:
        outputs.append(path)
        if existing:
            continue

        def emit(m: re.Match[str]) -> str:
            indent, site = m.group(1), m.group(2)
            return f'''{indent}{{ /* {MARKER} at {site} */
{indent}    static unsigned long long attempts = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&attempts, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 16u || (n & (n - 1u)) == 0u) {{
{indent}        const uint32_t obj = c->r[6];
{indent}        const uint32_t vt = obj >= 0x10000u
{indent}            && (uint64_t)obj + 4u <= GUEST_SIZE ? rd32(obj) : 0u;
{indent}        const uint32_t method = vt >= 0x10000u
{indent}            && (uint64_t)vt + 0x2cu <= GUEST_SIZE
{indent}            ? rd32(vt + 0x28u) : 0u;
{indent}        fprintf(stderr,
{indent}                "[reflex-ready-poll] pc={site} n=%llu value=%08x "
{indent}                "obj=%08x method=%08x keyA=%08x keyB=%08x "
{indent}                "esp=%08x\\n",
{indent}                (unsigned long long)n, c->r[0], obj, method,
{indent}                c->r[3], c->r[7], c->r[4]);
{indent}    }}
{indent}}}
''' + m.group(0)

        replaced = PATTERN.sub(emit, content)
        if "#include <stdio.h>" not in replaced:
            replaced = "#include <stdio.h>\n" + replaced
        matches[matches.index((path, content, existing))] = (path, replaced, False)
    # Do not modify generated sources until every critical anchor is found.
    for path, content, existing in matches:
        if not existing:
            path.write_text(content)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    files = patch_ready_poll(args.generated)
    print(f"Instrumented resource polling in {len(files)} translated chunk(s)")


if __name__ == "__main__":
    main()
