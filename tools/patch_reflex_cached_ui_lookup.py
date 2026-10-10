#!/usr/bin/env python3
"""Sample resource resolver returns in private cached Reflex translation."""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-ui-result-v1"
FUNCTION = "void fn_0084a890(X86 *c) {\n"
RET = re.compile(r"(?m)^([ \t]*)c->eip = rd32\(c->r\[4\]\); "
                 r"c->r\[4\] \+= 12u; recomp_return\(c\); return;  "
                 r"/\* 0084a9(0d|21) RET 0x8 \*/$")


def patch_lookup(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    hits = [(p, s) for p in chunks if (s := p.read_text()) and
            (FUNCTION in s or MARKER in s)]
    if len(hits) != 1:
        raise RuntimeError(f"Expected one resolver translation, found {len(hits)}")
    path, contents = hits[0]
    if MARKER in contents:
        if contents.count(MARKER) != 2 or contents.count("[reflex-ui-result]") != 2:
            raise RuntimeError("Malformed existing resolver trace")
        return path
    sites = sorted(m.group(2) for m in RET.finditer(contents))
    if contents.count(FUNCTION) != 1 or sites != ["0d", "21"]:
        raise RuntimeError(f"Missing translated resolver return sites: {sites}")

    def inject(m):
        indent, site = m.groups()
        trace = f'''{indent}{{   /* {MARKER} 0084a9{site} */
{indent}    static unsigned long long n = 0;
{indent}    const unsigned long long sample = __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
{indent}    if (sample <= 16u || (sample & (sample - 1u)) == 0u) {{
{indent}        const uint32_t sp = c->r[4];
{indent}        const uint32_t good = sp >= 0x10000u && (uint64_t)sp + 12u <= GUEST_SIZE;
{indent}        fprintf(stderr, "[reflex-ui-result] path={site} n=%llu caller=%08x key1=%08x key2=%08x result=%08x\\\\n",
{indent}                sample, good ? rd32(sp) : 0u,
{indent}                good ? rd32(sp + 4u) : 0u,
{indent}                good ? rd32(sp + 8u) : 0u, c->r[0]);
{indent}    }}
{indent}}}
'''
        return trace + m.group(0)

    contents = RET.sub(inject, contents)
    if "#include <stdio.h>" not in contents:
        contents = "#include <stdio.h>\n" + contents
    path.write_text(contents)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced translated resolver returns in {patch_lookup(args.generated).name}")


if __name__ == "__main__":
    main()
