#!/usr/bin/env python3
"""Replace cached packed-single traps with a reusable decoded x86 bridge.

The decoder covers common packed arithmetic, min/max, conversions and
SSE comparison predicates. Ghidra's private disassembly selects each site;
the runtime bridge independently checks the original instruction encoding.
Approximate reciprocal families, integer/MMX opcodes, MXCSR exception flags,
and other unsupported instructions deliberately retain explicit traps.

The generated chunks are private CI cache files, never committed. This patch
is idempotent and refuses to patch an empty or mismatched baseline.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import re

SUPPORTED = frozenset({
    "ADDPS", "MULPS", "SUBPS",
    "CVTPS2PD", "CVTPD2PS",
    "CMPNEQPS", "CMPLTPS", "CMPLEPS", "CMPEQPS",
    "CMPNLESS", "CMPNLESD",
    "DIVPS", "SQRTPS", "MINPS", "MAXPS",
})
TRAP = re.compile(
    r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x([0-9a-fA-F]+)u?\s*\)"
    r"\s*;\s*return\s*;", re.I
)
ASM = re.compile(r"^\s*([0-9a-fA-F]{8})\s{2,}([A-Za-z0-9_]+)\b")
INCLUDE = '#include "reflex_packed_sse.h"\n'
REPLACEMENT = "reflex_packed_sse(c, 0x{addr:08x}u);"


def load_mnemonics(folder: Path, addresses: set[int]) -> dict[int, str]:
    found = {}
    for path in sorted(folder.glob("*.asm")):
        for line in path.read_text(errors="replace").splitlines():
            match = ASM.match(line)
            if match:
                addr = int(match.group(1), 16)
                if addr in addresses:
                    found[addr] = match.group(2).upper()
    return found


def patch_cache(generated: Path, listing: Path) -> dict[str, int]:
    paths = sorted(generated.glob("chunk_*.c"))
    if not paths:
        raise RuntimeError(f"Missing private translation chunks in {generated}")
    by_chunk = {}
    addresses = set()
    for path in paths:
        code = path.read_text()
        hits = tuple(TRAP.finditer(code))
        by_chunk[path] = (code, hits)
        addresses.update(int(match.group(1), 16) for match in hits)
    # A fully patched translation may contain *no* remaining traps at all.
    # An idempotent second pass must accept that specific state, but an
    # unpatched/missing baseline still fails closed.
    if not addresses and any(INCLUDE in text for text, _ in by_chunk.values()):
        return {m: 0 for m in sorted(SUPPORTED)}
    kinds = load_mnemonics(listing, addresses)
    if not kinds:
        raise RuntimeError(f"Private disassembly missing or no opcode mappings: {listing}")

    counts = {m: 0 for m in sorted(SUPPORTED)}
    for path, (code, hits) in by_chunk.items():
        matching = [hit for hit in hits
                    if kinds.get(int(hit.group(1), 16)) in SUPPORTED]
        if not matching:
            continue

        def substitute(match: re.Match[str]) -> str:
            addr = int(match.group(1), 16)
            kind = kinds.get(addr)
            if kind not in SUPPORTED:
                return match.group(0)
            counts[kind] += 1
            return REPLACEMENT.format(addr=addr)

        patched = TRAP.sub(substitute, code)
        if INCLUDE not in patched:
            patched = INCLUDE + patched
        path.write_text(patched)

    # Idempotence on already patched chunks is intentional, but an entirely
    # unpatched baseline without previous shims indicates a mismatched input.
    if sum(counts.values()) == 0 and not any(
        INCLUDE in text for text, _ in by_chunk.values()
    ):
        raise RuntimeError("No packed-single traps matched the private listing")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", type=Path, default=Path("build/recomp/gen"))
    ap.add_argument("--asm", type=Path,
                    default=Path("analysis/decompiled/MXReflex.exe/functions"))
    args = ap.parse_args()
    counts = patch_cache(args.generated, args.asm)
    print("Reflex SIMD bulk bridge: " +
          ", ".join(f"{name}={n}" for name, n in sorted(counts.items())))


if __name__ == "__main__":
    main()
