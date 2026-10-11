#!/usr/bin/env python3
"""Trace 00543cd0 resource finalization return paths in cached x86-to-C output.

This is called after Intro.ENG resolves, by 005dbe50. The game repeats
005dbe50 when the result is zero. Preserve guest state; only print sparse
return-path samples. Private translated game source is never committed.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
FN = "void fn_00543cd0(X86 *c) {\n"
MARKER = "reflex-resource-finalize-v1"
RET = re.compile(
    r"(?m)^([ \t]*)c->eip = rd32\(c->r\[4\]\); "
    r"c->r\[4\] \+= 8u; recomp_return\(c\); return;  "
    r"/\* 00543d(92|a0) RET 0x4 \*/$"
)


def patch_finalize(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    found = [(f, code) for f in chunks
             if (code := f.read_text()) and (FN in code or MARKER in code)]
    if len(found) != 1:
        raise RuntimeError(f"Expected one 00543cd0 translation; got {len(found)}")
    file, code = found[0]
    if MARKER in code:
        if code.count(MARKER) != 2 or code.count("[reflex-resource-final]") != 2:
            raise RuntimeError("Malformed existing resource finalizer trace")
        return file
    sites = sorted(m.group(2) for m in RET.finditer(code))
    if code.count(FN) != 1 or sites != ["92", "a0"]:
        raise RuntimeError(f"Missing resource finalizer exits: {sites}")

    def trace(m):
        indent, site = m.group(1), m.group(2)
        trace_code = f'''{indent}{{ /* {MARKER} 00543d{site} */
{indent}    static unsigned long long n = 0;
{indent}    const unsigned long long count =
{indent}        __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
{indent}    if (count <= 16u || (count & (count - 1u)) == 0u) {{
{indent}        const uint32_t sp = c->r[4];
{indent}        const int safe = sp >= 0x10000u && (uint64_t)sp + 8u <= GUEST_SIZE;
{indent}        fprintf(stderr, "[reflex-resource-final] path={site} n=%llu caller=%08x arg0=%08x result=%08x ecx=%08x edx=%08x esi=%08x edi=%08x\\n",
{indent}                count, safe ? rd32(sp) : 0u, safe ? rd32(sp + 4u) : 0u,
{indent}                c->r[0], c->r[1], c->r[2], c->r[6], c->r[7]);
{indent}    }}
{indent}}}
'''
        return trace_code + m.group(0)

    code = RET.sub(trace, code)
    if "#include <stdio.h>" not in code:
        code = "#include <stdio.h>\n" + code
    file.write_text(code)
    return file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Instrumented resource finalizer in {patch_finalize(args.generated).name}")


if __name__ == "__main__":
    main()
