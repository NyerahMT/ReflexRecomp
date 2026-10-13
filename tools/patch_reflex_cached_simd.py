#!/usr/bin/env python3
"""Replace cached packed-single traps with a reusable decoded x86 bridge.

The decoder covers common packed arithmetic, min/max, conversions and
SSE comparison predicates. Ghidra's private disassembly selects each site;
the runtime bridge independently checks the original instruction encoding.
Integer/MMX opcodes, MXCSR exception flags,
and other unsupported instructions deliberately retain explicit traps.

The generated chunks are private CI cache files, never committed. This patch
is idempotent and refuses to patch an empty or mismatched baseline.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import re
import subprocess

SUPPORTED = frozenset({
    "ADDPS", "MULPS", "SUBPS",
    "CVTPS2PD", "CVTPD2PS",
    "CMPNEQPS", "CMPLTPS", "CMPLEPS", "CMPEQPS",
    "CMPNLESS", "CMPNLESD",
    "DIVPS", "SQRTPS", "MINPS", "MAXPS",
    "RCPPS", "RCPSS", "RSQRTPS",
    "MOVLHPS", "MOVHLPS",
    "CVTDQ2PS", "CVTPS2DQ", "PCMPGTD",
    "CVTPI2PS",
})
TRAP = re.compile(
    r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x([0-9a-fA-F]+)u?\s*\)"
    r"\s*;\s*return\s*;", re.I
)
ASM = re.compile(r"^\s*([0-9a-fA-F]{8})\s{2,}([A-Za-z0-9_]+)\b")
INCLUDE = '#include "reflex_packed_sse.h"\n'
REPLACEMENT = "reflex_packed_sse(c, 0x{addr:08x}u);"

# An exact-address, bounded private-PE disassembly supplements Ghidra's
# incomplete function listing. Never classify arbitrary bytes as SIMD:
# both the objdump mnemonic and the original prefix/opcode must agree.
OBJDUMP = re.compile(
    r"^\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)([A-Za-z0-9_]+)\b",
    re.M,
)
UNMAPPED_SUPPORTED = {
    "CVTPS2PD": (0x0f, 0x5a),
    "CVTPD2PS": (0x66, 0x0f, 0x5a),
}


def inspect_unknown_pe(exe: Path, addresses: set[int]) -> dict[int, str]:
    """Decode only trapped sites absent from Ghidra, never a whole PE."""
    if not exe.is_file():
        raise RuntimeError(f"Missing private executable: {exe}")
    if len(addresses) > 1024:
        raise RuntimeError("Refusing unbounded private PE opcode scan")
    found: dict[int, str] = {}
    for addr in sorted(addresses):
        output = subprocess.run(
            ["objdump", "-d", "-M", "intel",
             f"--start-address=0x{addr:x}",
             f"--stop-address=0x{addr + 16:x}", str(exe)],
            capture_output=True, text=True, check=False,
        )
        if output.returncode:
            continue
        for match in OBJDUMP.finditer(output.stdout):
            if int(match.group(1), 16) != addr:
                continue
            raw_bytes = tuple(int(x, 16) for x in match.group(2).split())
            name = match.group(3).upper()
            if name in UNMAPPED_SUPPORTED and (
                raw_bytes[:len(UNMAPPED_SUPPORTED[name])] ==
                UNMAPPED_SUPPORTED[name]
            ):
                found[addr] = name
            break
    return found



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


def patch_cache(generated: Path, listing: Path,
                exe: Path | None = None,
                expect_remaining: int | None = None) -> dict[str, int]:
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
    if exe is not None:
        extra = inspect_unknown_pe(exe, addresses - kinds.keys())
        kinds.update(extra)
        print("Reflex private PE instruction identification: " +
              ", ".join(f"{name}={sum(v == name for v in extra.values())}"
                        for name in sorted(set(extra.values()))))
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
    if expect_remaining is not None:
        remaining = sum(len(TRAP.findall(path.read_text())) for path in paths)
        if remaining != expect_remaining:
            raise RuntimeError(
                f"Expected {expect_remaining} leftover traps, found {remaining}"
            )
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", type=Path, default=Path("build/recomp/gen"))
    ap.add_argument("--asm", type=Path,
                    default=Path("analysis/decompiled/MXReflex.exe/functions"))
    ap.add_argument("--exe", type=Path,
                    help="Verified private PE for exact-PC fallback lookup")
    ap.add_argument("--expect-remaining", type=int, default=None)
    args = ap.parse_args()
    counts = patch_cache(args.generated, args.asm,
                         exe=args.exe, expect_remaining=args.expect_remaining)
    print("Reflex SIMD bulk bridge: " +
          ", ".join(f"{name}={n}" for name, n in sorted(counts.items())))


if __name__ == "__main__":
    main()
