#!/usr/bin/env python3
"""Trace the resource-map find result at guest 0054425B.

The Intro startup path reaches 00544220, which behaves like a map find:
005449d0 supplies a lower-bound candidate and 0054425B branches when that
candidate equals the container end sentinel. Sample the query string object
and container pointers without mutating guest state. Private translated game
source is never committed.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
FUNCTION = "void fn_00544220(X86 *c) {\n"
MARKER = "reflex-resource-find-v1"
BRANCH = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* 0054425b JZ\b)[^\n]*$"
)


def patch_find(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    hits = []
    for path in chunks:
        code = path.read_text()
        if FUNCTION in code or MARKER in code:
            hits.append((path, code))
    if len(hits) != 1:
        raise RuntimeError(f"Expected one 00544220 translation, found {len(hits)}")
    path, code = hits[0]
    if MARKER in code:
        if code.count(MARKER) != 1 or code.count("[reflex-resource-find]") != 1:
            raise RuntimeError("Malformed duplicate resource-find tracing")
        return path

    matches = list(BRANCH.finditer(code))
    if code.count(FUNCTION) != 1 or len(matches) != 1:
        raise RuntimeError(f"Expected one 0054425B branch, found {len(matches)}")

    def emit(m):
        indent = m.group(1)
        block = f'''{indent}{{ /* {MARKER} at 0054425b */
{indent}    static unsigned long long n = 0u;
{indent}    const unsigned long long count =
{indent}        __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
{indent}    if (count <= 16u || (count & (count - 1u)) == 0u) {{
{indent}        const uint32_t esi = c->r[6];
{indent}        const uint32_t edi = c->r[7];
{indent}        const uint32_t ebx = c->r[3];
{indent}        const uint32_t ebp = c->r[5];
{indent}        const int map_ok = esi >= 0x10000u
{indent}            && (uint64_t)esi + 0x1cu <= GUEST_SIZE;
{indent}        const int key_ok = ebp >= 0x10000u
{indent}            && (uint64_t)ebp + 0x1cu <= GUEST_SIZE;
{indent}        const uint32_t root = map_ok ? rd32(esi + 0x00u) : 0u;
{indent}        const uint32_t end = map_ok ? rd32(esi + 0x18u) : 0u;
{indent}        const uint32_t key_size = key_ok ? rd32(ebp + 0x14u) : 0u;
{indent}        const uint32_t key_cap = key_ok ? rd32(ebp + 0x18u) : 0u;
{indent}        uint32_t key_data = 0u;
{indent}        if (key_ok) {{
{indent}            key_data = key_cap >= 0x10u ? rd32(ebp + 0x04u) : ebp + 0x04u;
{indent}        }}
{indent}        const int data_ok = key_data >= 0x10000u
{indent}            && (uint64_t)key_data + 0x10u <= GUEST_SIZE;
{indent}        fprintf(stderr,
{indent}                "[reflex-resource-find] n=%llu esi=%08x root=%08x end=%08x "
{indent}                "candidate=%08x ebx=%08x candidate_is_end=%u keyobj=%08x "
{indent}                "key_size=%u key_cap=%u key_data=%08x key_words=%08x,%08x,%08x,%08x\\n",
{indent}                count, esi, root, end, edi, ebx,
{indent}                (unsigned)(edi == ebx), ebp, key_size, key_cap, key_data,
{indent}                data_ok ? rd32(key_data + 0x00u) : 0u,
{indent}                data_ok ? rd32(key_data + 0x04u) : 0u,
{indent}                data_ok ? rd32(key_data + 0x08u) : 0u,
{indent}                data_ok ? rd32(key_data + 0x0cu) : 0u);
{indent}    }}
{indent}}}
'''
        return block + m.group(0)

    code = BRANCH.sub(emit, code, count=1)
    if "#include <stdio.h>" not in code:
        code = "#include <stdio.h>\n" + code
    path.write_text(code)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced resource-map find state in {patch_find(args.generated).name}")


if __name__ == "__main__":
    main()
