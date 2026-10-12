#!/usr/bin/env python3
"""Follow the exact original MXTables callback branch at guest 0084ad8e.

The callback-scoped trace gets through 0084ad8e but records no instruction
inside its original 0084ad10..0084adff window afterwards. The instruction
starts with 0f 85 (JNE rel32). Read its actual destination from the private,
hash-verified PE rather than assuming the branch or callback stalled.
Only observes thread-local host diagnostic state; no guest code is changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/recomp/gen"
SOURCE_PC = "0084ad8e"
FALLTHROUGH_PC = "0084ad94"
MARKER = "reflex-callback-branch-v1"
FLAG = "reflex_type1_callback_trace_enabled"
LINE = re.compile(r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2}\s+)+\s*(\S+)(?:\s+(.*))?$")


def target_from_private_exe(exe: Path) -> int:
    if not exe.is_file():
        raise RuntimeError(f"Verified private Reflex EXE missing: {exe}")
    result = subprocess.run(
        ["objdump", "-d", "-M", "intel", "--start-address=0x0084ad8e",
         "--stop-address=0x0084ada0", str(exe)],
        check=True, text=True, capture_output=True,
    )
    candidates = []
    for row in result.stdout.splitlines():
        m = LINE.match(row)
        if m and int(m.group(1), 16) == int(SOURCE_PC, 16):
            candidates.append((m.group(2).lower(), (m.group(3) or "").strip()))
    if len(candidates) != 1:
        raise RuntimeError("Cannot resolve exact private guest 0084ad8e branch")
    mnemonic, operands = candidates[0]
    if mnemonic not in ("jne", "jnz"):
        raise RuntimeError(f"Unexpected 0084ad8e opcode: {mnemonic} {operands}")
    addr = re.match(r"^(?:0x)?([0-9a-fA-F]{6,8})(?:\b|$)", operands)
    if not addr:
        raise RuntimeError(f"Unparseable 0084ad8e branch operand: {operands}")
    target = int(addr.group(1), 16)
    if not 0x0084AD10 <= target < 0x00900000 or target == int(SOURCE_PC, 16):
        raise RuntimeError(f"Unexpected callback jump target: {target:08x}")
    return target


def patch_branch(generated: Path, target: int) -> tuple[list[Path], tuple[str, ...]]:
    if target == int(SOURCE_PC, 16) or target == int(FALLTHROUGH_PC, 16):
        raise RuntimeError("Source and destination guest PCs must be distinct")
    pcs = (SOURCE_PC, FALLTHROUGH_PC, f"{target:08x}")
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise RuntimeError(f"Missing generated code in {generated}")
    pattern = re.compile(
        r"(?m)^([ \t]*)(?=[^\n]*/\* (" +
        "|".join(pcs) + r")\b)[^\n]*$"
    )
    found = Counter()
    candidates = []
    for path in chunks:
        content = path.read_text()
        hits = [m.group(2) for m in pattern.finditer(content)]
        if hits or MARKER in content:
            candidates.append((path, content, hits))
            found.update(hits)
    if any(found[pc] != 1 for pc in pcs):
        raise RuntimeError(f"Missing/duplicate translated callback branch PCs: {dict(found)}")
    pending = []
    for path, content, hits in candidates:
        installed = MARKER in content
        if installed:
            if content.count("/* " + MARKER + " at ") != len(hits):
                raise RuntimeError(f"Partially installed callback branch probe: {path.name}")
            continue

        def instrument(m: re.Match[str]) -> str:
            indent, pc = m.group(1), m.group(2)
            return f'''{indent}{{ /* {MARKER} at {pc} */
{indent}    if ({FLAG}) {{
{indent}        static unsigned long long n_hits = 0u;
{indent}        const unsigned long long n =
{indent}            __atomic_add_fetch(&n_hits, 1u, __ATOMIC_RELAXED);
{indent}        if (n <= 12u || (n & (n - 1u)) == 0u) {{
{indent}            const uint32_t ebp = c->r[5];
{indent}            const int valid = ebp >= 0x10000u &&
{indent}                (uint64_t)ebp + 0x14u <= GUEST_SIZE;
{indent}            fprintf(stderr,
{indent}                    "[reflex-callback-branch] pc={pc} hit=%llu "
{indent}                    "eax=%08x ecx=%08x edx=%08x ebp=%08x "
{indent}                    "arg2=%08x esp=%08x\\n",
{indent}                    (unsigned long long)n, c->r[0], c->r[1],
{indent}                    c->r[2], ebp,
{indent}                    valid ? rd32(ebp + 0x10u) : 0xffffffffu,
{indent}                    c->r[4]);
{indent}        }}
{indent}    }}
{indent}}}
''' + m.group(0)

        modified = pattern.sub(instrument, content)
        if "#include <stdio.h>" not in modified:
            modified = "#include <stdio.h>\n" + modified
        if FLAG not in content:
            modified = f"extern __thread unsigned int {FLAG};\n" + modified
        pending.append((path, modified))
    # Transactional preflight before writing any generated chunk.
    for path, modified in pending:
        path.write_text(modified)
    return [path for path, _, _ in candidates], pcs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--exe", type=Path, required=True)
    p.add_argument("--generated", type=Path, default=GENERATED)
    p.add_argument("--output", type=Path,
                   default=Path("build/logs/reflex-callback-branch-target.txt"))
    args = p.parse_args()
    target = target_from_private_exe(args.exe)
    paths, pcs = patch_branch(args.generated, target)
    lines = [
        f"Real Reflex 0084ad8e JNE target: {target:08x}",
        f"Fallthrough: {FALLTHROUGH_PC}",
        f"Instrumented exact guest PCs: {', '.join(pcs)}",
        f"Translated chunks: {len(paths)}",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
