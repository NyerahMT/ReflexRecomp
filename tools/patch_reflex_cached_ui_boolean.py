#!/usr/bin/env python3
"""Trace the Boolean result of the UI resolver wrapper in private cached C.

Original x86: 0084a840 calls vtable +0x20 (resource resolver),
then NEG EAX; SBB EAX,EAX; NEG EAX; RET 8 at 0084a857.
If a nonnull resource is found, this wrapper must return EAX=1.
Instrumentation does not alter the guest's execution or flags.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
FUNCTION = "void fn_0084a840(X86 *c) {\n"
MARKER = "reflex-ui-boolean-v1"
RETURN = re.compile(
    r"(?m)^([ \t]*)c->eip = rd32\(c->r\[4\]\); "
    r"c->r\[4\] \+= 12u; recomp_return\(c\); return;  "
    r"/\* 0084a857 RET 0x8 \*/$"
)


def patch_boolean(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    found = [(file, source) for file in chunks
             if (source := file.read_text()) and
             (FUNCTION in source or MARKER in source)]
    if len(found) != 1:
        raise RuntimeError(f"Expected one UI Boolean wrapper; got {len(found)}")
    file, source = found[0]
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count("[reflex-ui-boolean]") != 1:
            raise RuntimeError("Malformed or duplicate UI Boolean tracing")
        return file
    if source.count(FUNCTION) != 1 or len(RETURN.findall(source)) != 1:
        raise RuntimeError("Missing translated UI Boolean return at 0084a857")

    def inject(match):
        indent = match.group(1)
        return (f"""{indent}{{ /* {MARKER} */
{indent}    static unsigned long long n = 0;
{indent}    const unsigned long long count =
{indent}        __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
{indent}    if (count <= 16u || (count & (count - 1u)) == 0u) {{
{indent}        const uint32_t sp = c->r[4];
{indent}        const int valid = sp >= 0x10000u && (uint64_t)sp + 12u <= GUEST_SIZE;
{indent}        fprintf(stderr,
{indent}                "[reflex-ui-boolean] n=%llu caller=%08x key1=%08x key2=%08x eax=%08x\\n",
{indent}                count, valid ? rd32(sp) : 0u,
{indent}                valid ? rd32(sp + 4u) : 0u,
{indent}                valid ? rd32(sp + 8u) : 0u, c->r[0]);
{indent}    }}
{indent}}}
""" + match.group(0))
    source = RETURN.sub(inject, source)
    if "#include <stdio.h>" not in source:
        source = "#include <stdio.h>\n" + source
    file.write_text(source)
    return file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced UI Boolean wrapper at {patch_boolean(args.generated).name}")


if __name__ == "__main__":
    main()
