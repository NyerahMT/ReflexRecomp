#!/usr/bin/env python3
"""Sample the two early-exit branch decisions in Reflex resource finalizer.

Original guest 00543cd0 returns EAX=0 repeatedly on the Intro startup path.
The optional resource virtual calls were not observed in the preceding trace,
so measure the CMP/JZ gates at 00543d31 and 00543d45. This changes no
guest registers or flags and fails closed if translation anchors drift.
Only instrument private generated sources, never commit game translations.
"""
import argparse
from pathlib import Path
import re

GENERATED = Path(__file__).resolve().parents[1] / "build/recomp/gen"
FUNCTION = "void fn_00543cd0(X86 *c) {\n"
MARKER = "reflex-resource-gates-v1"
GATES = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* 00543d(31|45) JZ\b)[^\n]*$"
)


def patch_gates(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError("No cached translation chunks")
    hits = []
    for path in chunks:
        code = path.read_text()
        if FUNCTION in code or MARKER in code:
            hits.append((path, code))
    if len(hits) != 1:
        raise RuntimeError(f"Expected one 00543cd0 translation, found {len(hits)}")
    path, code = hits[0]
    if MARKER in code:
        if code.count(MARKER) != 2 or code.count("[reflex-resource-gate]") != 2:
            raise RuntimeError("Malformed duplicate branch tracing")
        return path
    sites = sorted(m.group(2) for m in GATES.finditer(code))
    if code.count(FUNCTION) != 1 or sites != ["31", "45"]:
        raise RuntimeError(f"Expected early JZ gate comments 31/45, got {sites}")

    def emit(m):
        indent, gate = m.group(1), m.group(2)
        code_block = f'''{indent}{{ /* {MARKER} at 00543d{gate} */
{indent}    static unsigned long long n = 0u;
{indent}    const unsigned long long count =
{indent}        __atomic_add_fetch(&n, 1u, __ATOMIC_RELAXED);
{indent}    if (count <= 16u || (count & (count - 1u)) == 0u) {{
{indent}        const uint32_t sp = c->r[4];
{indent}        const uint32_t esi = c->r[6];
{indent}        const uint32_t edi = c->r[7];
{indent}        const int stack_ok = sp >= 0x10000u
{indent}            && (uint64_t)sp + 0x14u <= GUEST_SIZE;
{indent}        const int state_ok = esi >= 0x10000u
{indent}            && (uint64_t)esi + 0x28u <= GUEST_SIZE;
{indent}        const uint32_t local = stack_ok ? rd32(sp + 0x10u) : 0u;
{indent}        const uint32_t state = state_ok ? rd32(esi + 0x24u) : 0u;
{indent}        fprintf(stderr,
{indent}                "[reflex-resource-gate] site={gate} n=%llu local=%08x edi=%08x equal=%u "
{indent}                "esi=%08x state24=%08x state_zero=%u sp=%08x eax=%08x\\n",
{indent}                count, local, edi, (unsigned)(local == edi),
{indent}                esi, state, (unsigned)(state == 0u), sp, c->r[0]);
{indent}    }}
{indent}}}
'''
        return code_block + m.group(0)
    code = GATES.sub(emit, code)
    if "#include <stdio.h>" not in code:
        code = "#include <stdio.h>\n" + code
    path.write_text(code)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    print(f"Traced both early resource-finalizer gates in {patch_gates(args.generated).name}")


if __name__ == "__main__":
    main()
