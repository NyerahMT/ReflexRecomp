#!/usr/bin/env python3
"""Identify untranslated guest instruction mnemonics absent from Ghidra listings.

Only previously audited <not-mapped> guest PCs are decoded from a verified
private PE. The report contains only an address and mnemonic for each site;
no instruction bytes, executable contents, or full disassembly are emitted.
An objdump failure remains UNRESOLVED, not a claimed translation fix.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import subprocess

UNMAPPED = re.compile(r"^([0-9a-fA-F]{8})\s+<not-mapped>\s+\S+\s*$")
LINE = re.compile(r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2}\s+)+(\S+)(?:\s+.*)?$")
UNKNOWN = frozenset({"(bad)", ".byte", "data16", "rex", "rex.w"})


def missing_sites(report: str) -> list[int]:
    """Only use unresolved PCs from the explicit static audit section."""
    if "Sites (address | mnemonic | generated chunk)" not in report:
        raise ValueError("Incomplete translation-trap audit: missing site table")
    sites = {
        int(m.group(1), 16)
        for line in report.split("Sites (address | mnemonic | generated chunk)", 1)[1].splitlines()
        if (m := UNMAPPED.fullmatch(line.strip()))
    }
    return sorted(sites)


def decode_one(exe: Path, pc: int) -> str | None:
    """Use only one instruction at the exact audited PC, not nearby code."""
    run = subprocess.run(
        ["objdump", "-d", "-M", "intel",
         f"--start-address=0x{pc:x}", f"--stop-address=0x{pc+16:x}",
         str(exe)],
        capture_output=True, text=True, check=False,
    )
    if run.returncode != 0:
        return None
    for line in run.stdout.splitlines():
        m = LINE.match(line)
        if m and int(m.group(1), 16) == pc:
            name = m.group(2).upper()
            return name if name.lower() not in UNKNOWN else None
    return None


def audit(trap_report: Path, exe: Path) -> str:
    if not trap_report.is_file() or not exe.is_file():
        raise FileNotFoundError("Both the cached trap report and verified private PE are required")
    addresses = missing_sites(trap_report.read_text(errors="replace"))
    if len(addresses) > 1024:
        raise ValueError("Unexpected number of unmapped traps; refusing unbounded disassembly")
    rows = [(pc, decode_one(exe, pc)) for pc in addresses]
    counts = Counter(name or "<unresolved>" for _, name in rows)
    text = [
        "Unidentified original Reflex guest instruction inventory",
        f"Audited unmapped sites: {len(rows)}",
        f"Newly identified by exact-PC objdump: {sum(name is not None for _, name in rows)}",
        f"Still unresolved: {sum(name is None for _, name in rows)}",
        "Mnemonic groups (sites):",
    ]
    text.extend(f"  {name}: {count}" for name, count in sorted(counts.items()))
    text += ["Site mnemonics (PC mnemonic; no bytes or game binary):"]
    text.extend(f"  {pc:08x}  {name or '<unresolved>'}" for pc, name in rows)
    text += ["Unexecuted sites are not necessarily runtime blockers.",
             "Objdump mnemonics require manual comparison against true guest bytes before patching."]
    return "\n".join(text) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trap-report", type=Path, required=True)
    p.add_argument("--exe", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = audit(a.trap_report, a.exe)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(report)
    print(report, end="")


if __name__ == "__main__":
    main()
