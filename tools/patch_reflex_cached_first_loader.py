#!/usr/bin/env python3
"""Trace the first never-returning Reflex loader initializer (004e6c30).

Grounded in the user's original MXReflex.exe. The previous real runtime reaches
0075ed6f (CALL 004e6c30) and no subsequent loader stage. This instruments
genuine translated instruction comments inside 004e6c30, independently of
the translator's fn_* vs body_* representation or chunk partitioning.

Read-only: no changes to registers, flags, memory, thread state or events.
Translated game files are private build inputs and must not be committed.
"""
from collections import Counter
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-first-loader-stage-v1"
STAGES = (
    "004e6c48",  # first kernel32 call
    "004e6c6d",  # first CRT helper
    "004e6c91",  # first resource virtual call
    "004e6cb0",  # resource initialization call
    "004e6cd2",  # subsequent resource lookup
    "004e6ceb",  # subsequent resource virtual call
    "004e6d32",  # data stream initialization
    "004e6d37",  # data archive initialization
    "004e6d91",  # resource operation
    "004e6daf",  # first resource query
    "004e6de4",  # next resource query
    "004e6e53",  # subsequent resource query
    "004e6efc",  # late virtual resource query
    "004e6f1d",  # last local resource routine
    "004e6f22",  # final kernel32 call
    "004e6f35",  # final CRT check
    "004e6f40",  # return to 0075ed74
)
REQUIRED = {"004e6c48", "004e6c6d", "004e6c91"}
RE = re.compile(r"(?m)^([ \t]*)(?=[^\n]*/\* (" + "|".join(STAGES) +
                r")\b)[^\n]*$")


def patch_stages(generated: Path) -> list[Path]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"No translated chunks under {generated}")
    patches = []
    sites = []
    for path in chunks:
        text = path.read_text()
        if MARKER in text:
            # A pre-existing partial patch is never acceptable.
            count = text.count(MARKER)
            nlines = text.count("[reflex-first-loader]")
            if count != nlines or count == 0:
                raise RuntimeError(f"Malformed prior patch in {path.name}")
            patches.append((path, text, True))
            for m in RE.finditer(text):
                sites.append(m.group(2))
            continue
        matches = list(RE.finditer(text))
        if not matches:
            continue
        sites.extend(m.group(2) for m in matches)
        patches.append((path, text, False))

    counts = Counter(sites)
    if not REQUIRED.issubset(counts) or any(counts[x] != 1 for x in counts):
        raise RuntimeError(f"Original loader checkpoints missing/duplicated: "
                           f"required={sorted(REQUIRED)}, found={dict(counts)}")

    outputs = []
    for path, source, existing in patches:
        if existing:
            if source.count(MARKER) != len(RE.findall(source)):
                raise RuntimeError(f"Partial prior instrumentation: {path.name}")
            outputs.append(path)
            continue

        def add(m):
            indent, pc = m.group(1), m.group(2)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long samples = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&samples, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}        fprintf(stderr,
{indent}                "[reflex-first-loader] pc={pc} n=%llu eax=%08x ebx=%08x ecx=%08x "
{indent}                "esi=%08x edi=%08x esp=%08x\\n",
{indent}                (unsigned long long)n,
{indent}                c->r[0], c->r[3], c->r[1], c->r[6], c->r[7], c->r[4]);
{indent}    }}
{indent}}}
''' + m.group(0)

        target = RE.sub(add, source)
        if "#include <stdio.h>" not in target:
            target = "#include <stdio.h>\n" + target
        outputs.append(path)
        patches[patches.index((path, source, existing))] = (path, target, False)

    # All source anchors validated, only now write modified private code.
    for path, content, existing in patches:
        if not existing:
            path.write_text(content)
    print(f"Traced {len(sites)}/17 checkpoints across {len(outputs)} chunk(s)")
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    patch_stages(args.generated)


if __name__ == "__main__":
    main()
