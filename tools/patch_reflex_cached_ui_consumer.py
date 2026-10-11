#!/usr/bin/env python3
"""Sample calls into the translated 005dbe50 localized-resource consumer.

The 005dbe99 call to virtual resource slot +0x24 already returns EAX=1
in the Intro.ENG experiment. Record the *outer* caller that invokes this
function repeatedly, rather than patching the proven-correct Boolean path.
Only the generated cached translation is modified.
"""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
MARKER = "reflex-ui-consumer-entry-v1"
ANCHOR = re.compile(
    r"(?m)^([ \t]*)void fn_005dbe50\(X86 \*c\) \{\n"
)
TRACE = r"""
    /* reflex-ui-consumer-entry-v1: original guest 005dbe50 call trace. */
    {
        static unsigned long long n = 0u;
        const unsigned long long count =
            __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
        if (count <= 32u || (count & (count - 1u)) == 0u) {
            const uint32_t sp = c->r[4];
            const int safe = sp >= 0x10000u && (uint64_t)sp + 8u <= GUEST_SIZE;
            fprintf(stderr,
                    "[reflex-ui-consumer] n=%llu caller=%08x arg0=%08x "
                    "esp=%08x eax=%08x ecx=%08x edi=%08x esi=%08x\n",
                    count, safe ? rd32(sp) : 0u,
                    safe ? rd32(sp + 4u) : 0u,
                    sp, c->r[0], c->r[1], c->r[7], c->r[6]);
        }
    }
"""


def patch_consumer(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    matches = []
    for path in chunks:
        source = path.read_text()
        if ANCHOR.search(source) or MARKER in source:
            matches.append((path, source))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one translated consumer body, found {len(matches)}")
    path, source = matches[0]
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count("[reflex-ui-consumer]") != 1:
            raise RuntimeError("Malformed existing consumer trace")
        return path
    if len(ANCHOR.findall(source)) != 1:
        raise RuntimeError("Consumer entry anchor missing")
    source = ANCHOR.sub(lambda m: m.group(0) + TRACE, source, count=1)
    if "#include <stdio.h>" not in source:
        source = "#include <stdio.h>\n" + source
    path.write_text(source)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced outer UI caller in {patch_consumer(args.generated).name}")


if __name__ == "__main__":
    main()
