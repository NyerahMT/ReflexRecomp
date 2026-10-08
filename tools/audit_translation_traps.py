#!/usr/bin/env python3
"""Inventory all remaining unmodelled x86 opcodes in cached Reflex translation.

This scans the already-generated private chunks, not game binary data. It
records each remaining recomp_unmodelled() site with the Ghidra mnemonic if
available, and groups unsupported instructions by mnemonic so broad opcode
coverage can replace one-address-at-a-time patches.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re

TRAP = re.compile(r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x([0-9a-fA-F]+)u?\s*\)")
ASM = re.compile(r"^\s*([0-9a-fA-F]{8})\s{2,}(\S+)\s*(.*)$")


def collect_traps(generated: Path) -> dict[int, str]:
    chunks = sorted(generated.glob("chunk_*.c"))
    if not chunks:
        raise ValueError(f"No generated translation chunks under {generated}")
    result: dict[int, str] = {}
    for chunk in chunks:
        for match in TRAP.finditer(chunk.read_text(errors="replace")):
            address = int(match.group(1), 16)
            result[address] = chunk.name
    return result


def collect_mnemonics(asm_directory: Path, addresses: set[int]) -> dict[int, str]:
    found = {}
    if not addresses or not asm_directory.exists():
        return found
    # Parse each source listing exactly once. Keep only rows for abort sites;
    # the full private disassembly never leaves CI.
    for path in sorted(asm_directory.glob("*.asm")):
        for line in path.read_text(errors="replace").splitlines():
            m = ASM.match(line)
            if m:
                address = int(m.group(1), 16)
                if address in addresses:
                    found[address] = m.group(2).upper()
    return found


def render_audit(traps: dict[int, str], mnemonics: dict[int, str]) -> str:
    totals = Counter(mnemonics.get(addr, "<not-mapped>") for addr in traps)
    lines = [
        "Reflex cached-translation unsupported-instruction inventory",
        f"Unmodelled guest instruction sites: {len(traps)}",
        f"Resolved guest mnemonics: {len(mnemonics)}",
        "",
        "Instruction groups (count | mnemonic)",
    ]
    lines.extend(f"{n:6d}  {name}" for name, n in totals.most_common())
    lines.append("")
    lines.append("Sites (address | mnemonic | generated chunk)")
    lines.extend(f"{addr:08x}  {mnemonics.get(addr, '<not-mapped>'):16} {traps[addr]}"
                 for addr in sorted(traps))
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--generated", type=Path, default=Path("build/recomp/gen"))
    p.add_argument("--asm", type=Path,
                   default=Path("analysis/decompiled/MXReflex.exe/functions"))
    p.add_argument("--output", type=Path,
                   default=Path("build/logs/translation-trap-audit.txt"))
    args = p.parse_args()
    traps = collect_traps(args.generated)
    mnemonics = collect_mnemonics(args.asm, set(traps))
    report = render_audit(traps, mnemonics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print("\n".join(report.splitlines()[:25]))
    print(f"Full audit: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
