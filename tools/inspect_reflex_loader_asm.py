#!/usr/bin/env python3
"""Report only the original instructions around a blocked Reflex guest PC.

Reads private Ghidra .asm listings in CI and emits a tightly bounded
instruction window, never a full function, translation or game asset.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ASM = re.compile(r"^\s*([0-9a-fA-F]{8})\s{2,}(\S+)(?:\s+(.*))?$")
DEFAULT_START = 0x0084BE11
DEFAULT_END = 0x0084BE49
REQUIRED = (0x0084BE35, 0x0084BE40)


def read_window(asm_dir: Path, start: int = DEFAULT_START,
                end: int = DEFAULT_END) -> list[tuple[int, str, str]]:
    if not asm_dir.is_dir():
        raise RuntimeError(f"Private Ghidra ASM directory missing: {asm_dir}")
    if start > end or end - start > 0x100:
        raise ValueError("Instruction report must cover at most 257 guest bytes")
    results: dict[int, tuple[str, str]] = {}
    sources: dict[int, Path] = {}
    for path in sorted(asm_dir.glob("*.asm")):
        for line in path.read_text(errors="replace").splitlines():
            match = ASM.match(line)
            if not match:
                continue
            pc = int(match.group(1), 16)
            if start <= pc <= end:
                if pc in results:
                    raise RuntimeError(f"Duplicate guest PC {pc:08x}: {sources[pc].name}, {path.name}")
                mnemonic, operands = match.group(2), (match.group(3) or "").strip()
                results[pc] = (mnemonic, operands[:128])
                sources[pc] = path
    missing = [pc for pc in REQUIRED if start <= pc <= end and pc not in results]
    if missing:
        raise RuntimeError("Missing required guest PCs: " + ", ".join(f"{pc:08x}" for pc in missing))
    return [(pc, *results[pc]) for pc in sorted(results)]


def render(window: list[tuple[int, str, str]]) -> str:
    lines = ["Reflex original type-1 loader instruction window (diagnostic only)",
             "No game asset or full source listing is included."]
    lines.extend(f"{pc:08x}  {mnemonic:12} {operands}" for pc, mnemonic, operands in window)
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--asm", type=Path,
                   default=Path("analysis/decompiled/MXReflex.exe/functions"))
    p.add_argument("--output", type=Path,
                   default=Path("build/logs/type1-loader-asm-window.txt"))
    args = p.parse_args()
    report = render(read_window(args.asm))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
