#!/usr/bin/env python3
"""Trace resource-tree comparator results without changing guest control flow.

The lower-bound helper at 005449d0 calls the imported key comparator at
00544a13. Its result is tested at 00544a18; arguments remain in the
just-popped guest stack words at ESP-8 and ESP-4. Capture those arguments
and short read-only previews to distinguish a bad comparison from an
empty or incorrectly traversed tree.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
FUNCTION = "void fn_005449d0(X86 *c) {\n"
MARKER = "reflex-resource-cmp-v1"
SITE = re.compile(r"(?m)^([ \t]*)(?=[^\n]*/\* 00544a18 TEST\b)[^\n]*$")


def patch_cmp(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    hits = [(p, s) for p in chunks if FUNCTION in (s := p.read_text()) or MARKER in s]
    if len(hits) != 1:
        raise RuntimeError(f"Expected one 005449d0 translation, found {len(hits)}")
    path, source = hits[0]
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count("[reflex-resource-cmp]") != 1:
            raise RuntimeError("Malformed duplicate resource-comparator tracing")
        return path
    matches = list(SITE.finditer(source))
    if source.count(FUNCTION) != 1 or len(matches) != 1:
        raise RuntimeError(f"Expected one 00544A18 TEST site, found {len(matches)}")

    def inject(match):
        i = match.group(1)
        return f'''{i}{{ /* {MARKER} at 00544a18 */
{i}    static unsigned long long compare_count = 0u;
{i}    const unsigned long long n =
{i}        __atomic_add_fetch(&compare_count, 1u, __ATOMIC_RELAXED);
{i}    if (n <= 16u || (n & (n - 1u)) == 0u) {{
{i}        const uint32_t esp = c->r[4];
{i}        const int stack_ok = esp >= 0x10008u && (uint64_t)esp <= GUEST_SIZE;
{i}        const uint32_t lhs = stack_ok ? rd32(esp - 8u) : 0u;
{i}        const uint32_t rhs = stack_ok ? rd32(esp - 4u) : 0u;
{i}        const int lhs_ok = lhs >= 0x10000u && (uint64_t)lhs + 8u <= GUEST_SIZE;
{i}        const int rhs_ok = rhs >= 0x10000u && (uint64_t)rhs + 8u <= GUEST_SIZE;
{i}        fprintf(stderr,
{i}                "[reflex-resource-cmp] n=%llu eax=%08x cmp=%d esp=%08x "
{i}                "lhs=%08x rhs=%08x lhs_bytes=%08x,%08x rhs_bytes=%08x,%08x\\n",
{i}                n, c->r[0], (int32_t)c->r[0], esp, lhs, rhs,
{i}                lhs_ok ? rd32(lhs) : 0u, lhs_ok ? rd32(lhs + 4u) : 0u,
{i}                rhs_ok ? rd32(rhs) : 0u, rhs_ok ? rd32(rhs + 4u) : 0u);
{i}    }}
{i}}}
''' + match.group(0)

    source = SITE.sub(inject, source, count=1)
    if "#include <stdio.h>" not in source:
        source = "#include <stdio.h>\n" + source
    path.write_text(source)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced resource comparator in {patch_cmp(args.generated).name}")


if __name__ == "__main__":
    main()
