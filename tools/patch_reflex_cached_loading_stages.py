#!/usr/bin/env python3
"""Measure real Reflex loading worker execution checkpoints in generated x86-to-C.

From the user's original MXReflex.exe:
  00760400 calls 0075ed60
  0075ed60 executes a staged initialization and signals LoadingThreadEvent
  via IAT KERNEL32!SetEvent at 0075f293.

This patch observes selected unmodified guest instruction addresses. It never
forces a thread to run, skips game initialization, or signals completion.
Only private generated code is patched; do not check translated game source
or original game assets into the public repository.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
FUNCTION = "void fn_0075ed60(X86 *c) {\n"
MARKER = "reflex-loading-stage-v1"

# These addresses are taken from the original executable's disassembly.
# They bracket meaningful initialization stages and the eventual SetEvent.
STAGES = (
    "0075ed6f",  # entry -> 004e6c30
    "0075ed74",  # resource-system context -> 00760410
    "0075edaf",  # resource initialization -> 00540610
    "0075eee2",  # late initial object setup -> 00547270
    "0075ef00",  # first loading handshake (WaitForSingleObject)
    "0075ef33",  # subsequent asset/controller initialization
    "0075f130",  # late memory allocation
    "0075f23b",  # late game asset load operation
    "0075f293",  # completion signal (SetEvent)
)
TARGET = re.compile(
    r"(?m)^([ \t]*)(?=[^\n]*/\* ("
    + "|".join(STAGES)
    + r")\b)[^\n]*$"
)


def patch_loading_stages(generated: Path) -> Path:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"No cached translation chunks in {generated}")

    found = [(path, source) for path in chunks
             if (source := path.read_text()) and
             (FUNCTION in source or MARKER in source)]
    if len(found) != 1:
        raise RuntimeError(f"Expected one 0075ed60 translation, got {len(found)}")
    path, source = found[0]
    if MARKER in source:
        if source.count(MARKER) != len(STAGES) or \
                source.count("[reflex-load-stage]") != len(STAGES):
            raise RuntimeError("Incomplete existing loading-stage patch")
        return path

    sites = [m.group(2) for m in TARGET.finditer(source)]
    if source.count(FUNCTION) != 1 or sorted(sites) != sorted(STAGES):
        raise RuntimeError(f"Expected exactly {STAGES}; actual={sites}")

    def emit(match: re.Match[str]) -> str:
        indent, pc = match.group(1), match.group(2)
        # Do not read stack/worker object from unvalidated guest ranges.
        return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    static unsigned long long samples = 0u;
{indent}    const unsigned long long n =
{indent}        __atomic_add_fetch(&samples, 1u, __ATOMIC_RELAXED);
{indent}    if (n <= 8u || (n & (n - 1u)) == 0u) {{
{indent}        const uint32_t ebx = c->r[3];
{indent}        const uint32_t sp = c->r[4];
{indent}        const int object_ok = ebx >= 0x10000u &&
{indent}            (uint64_t)ebx + 0x161fcu <= GUEST_SIZE;
{indent}        fprintf(stderr,
{indent}                "[reflex-load-stage] pc={pc} n=%llu ebx=%08x "
{indent}                "esp=%08x eax=%08x ecx=%08x status_event=%08x "
{indent}                "worker_event=%08x\\\\n",
{indent}                (unsigned long long)n, ebx, sp,
{indent}                c->r[0], c->r[1],
{indent}                object_ok ? rd32(ebx + 0x161f4u) : 0u,
{indent}                object_ok ? rd32(ebx + 0x161f8u) : 0u);
{indent}    }}
{indent}}}
''' + match.group(0)

    patched = TARGET.sub(emit, source)
    if "#include <stdio.h>" not in patched:
        patched = "#include <stdio.h>\n" + patched
    path.write_text(patched)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=Path, default=GENERATED)
    args = parser.parse_args()
    path = patch_loading_stages(args.generated)
    print(f"Installed {len(STAGES)} loader checkpoints in {path.name}")


if __name__ == "__main__":
    main()
