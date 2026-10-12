#!/usr/bin/env python3
"""Track the original 0084ad10 callback only for the stuck one-entry resource.

0084beef calls EDX=0084ad10, then normally resumes at 0084bef1.
Unlike earlier power-of-two logging shared by every resource, this sets a
thread-local *host diagnostic flag* only for the count=1/base=0 loader.
The flag never modifies guest memory, registers or readiness state.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

GENERATED = Path(__file__).resolve().parents[1] / "build/recomp/gen"
MARKER = "reflex-type1-callback-v1"
SYMBOL = "reflex_type1_callback_trace_enabled"
FIRST = int("0084ad10", 16)
LAST = int("0084adff", 16)
ENTRY = "0084beef"
RETURN = "0084bf12"
REQUIRED = {"0084ad10", ENTRY, RETURN}
PATTERN = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* (0084ad[0-9a-f]{2}|0084beef|0084bf12)\b)[^\n]*$"
)


def patch_callback(generated: Path) -> tuple[list[Path], list[str]]:
    files = sorted(generated.glob("chunk_*.c"))
    if not files:
        raise RuntimeError(f"Missing generated translation chunks: {generated}")

    sites = Counter()
    chunks = []
    for path in files:
        text = path.read_text()
        hits = [m.group(2) for m in PATTERN.finditer(text)
                if FIRST <= int(m.group(2), 16) <= LAST or
                m.group(2) in (ENTRY, RETURN)]
        if hits or MARKER in text:
            chunks.append((path, text, hits))
            sites.update(hits)
    if not REQUIRED.issubset(sites) or any(n != 1 for n in sites.values()):
        raise RuntimeError(f"Missing/duplicate type-1 callback PCs: {dict(sites)}")

    definition = next(path for path, _, hits in chunks if ENTRY in hits)
    pending = []
    for path, source, hits in chunks:
        installed = MARKER in source
        if installed:
            if source.count("/* " + MARKER + " at ") != len(hits):
                raise RuntimeError(f"Partial callback PC instrumentation in {path.name}")
            if source.count(SYMBOL + ";") + source.count(SYMBOL + " = 0u;") != 1:
                raise RuntimeError(f"Partial callback trace declaration in {path.name}")
            continue

        def instrument(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            if pc == ENTRY:
                return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    const uint32_t obj = c->r[3];
{indent}    const int valid = obj >= 0x10000u &&
{indent}        (uint64_t)obj + 0x98u <= GUEST_SIZE;
{indent}    {SYMBOL} = valid &&
{indent}        rd32(obj + 0x84u) == 1u &&
{indent}        rd32(obj + 0x90u) == 0u;
{indent}    if ({SYMBOL})
{indent}        fprintf(stderr, "[reflex-callback] enter pc={pc} "
{indent}                "target=%08x obj=%08x esp=%08x\\n",
{indent}                c->r[2], obj, c->r[4]);
{indent}}}
''' + m.group(0)
            if pc == RETURN:
                return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    if ({SYMBOL})
{indent}        fprintf(stderr, "[reflex-callback] returned pc={pc} "
{indent}                "eax=%08x esp=%08x\\n", c->r[0], c->r[4]);
{indent}    {SYMBOL} = 0u;
{indent}}}
''' + m.group(0)
            if not FIRST <= int(pc, 16) <= LAST:
                return m.group(0)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    if ({SYMBOL}) {{
{indent}        static unsigned long long callback_hits = 0u;
{indent}        const unsigned long long n =
{indent}            __atomic_add_fetch(&callback_hits, 1u, __ATOMIC_RELAXED);
{indent}        if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}            const uint32_t sp = c->r[4];
{indent}            const int valid = sp >= 0x10000u &&
{indent}                (uint64_t)sp + 12u <= GUEST_SIZE;
{indent}            fprintf(stderr,
{indent}                    "[reflex-callback] pc={pc} hit=%llu "
{indent}                    "eax=%08x ebx=%08x ecx=%08x edx=%08x "
{indent}                    "esi=%08x edi=%08x esp=%08x sp0=%08x\\n",
{indent}                    (unsigned long long)n, c->r[0], c->r[3],
{indent}                    c->r[1], c->r[2], c->r[6], c->r[7],
{indent}                    sp, valid ? rd32(sp) : 0xffffffffu);
{indent}        }}
{indent}    }}
{indent}}}
''' + m.group(0)

        replacement = PATTERN.sub(instrument, source)
        if "#include <stdio.h>" not in replacement:
            replacement = "#include <stdio.h>\n" + replacement
        declaration = ("__thread unsigned int " + SYMBOL + " = 0u;\n"
                       if path == definition else
                       "extern __thread unsigned int " + SYMBOL + ";\n")
        replacement = declaration + replacement
        pending.append((path, replacement))
    for path, replacement in pending:
        path.write_text(replacement)
    return [path for path, _, _ in chunks], sorted(sites)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--generated", type=Path, default=GENERATED)
    args = p.parse_args()
    files, pcs = patch_callback(args.generated)
    print(f"Callback 0084ad10 scoped probe installed ({len(pcs)} PCs; "
          f"{len(files)} chunks)")


if __name__ == "__main__":
    main()
