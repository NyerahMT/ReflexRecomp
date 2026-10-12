#!/usr/bin/env python3
"""Compare normal and longer original-game startup probes without faking progress.

The translated guest instruction probes log the first 12 visits to each PC
and then powers of two. The highest observed hit per PC is a lower bound on
executions. Do NOT treat the largest PC address or CI success as completion.
No game code, assets or guest state are read or changed here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

ENTRY = re.compile(
    r"\[reflex-mxtables-inner\] pc=([0-9a-f]{8}) hit=(\d+)\b"
)
SINGLE = re.compile(
    r"\[reflex-type1-single\] pc=([0-9a-f]{8}) hit=(\d+)\b"
)
MARKERS = (
    "004eefa0",  # parser entry
    "004ef3c1",  # known repeating parser segment
    "004ef52e",  # next loop iteration
    "004ef58a",  # last observed inner-PC in run #38269335712
    "004ef73e",  # furthest address observed, not necessarily last
)
RETURNED = ("004f019e", "0084bf12", "0084bfb8")


@dataclass(frozen=True)
class Sample:
    total_lines: int
    unique_decoder_pcs: int
    max_hit_by_pc: dict[str, int]
    single_hits: dict[str, int]


def sample(content: str) -> Sample:
    counts: dict[str, int] = {}
    single: dict[str, int] = {}
    # Use max emitted checkpoint counter, not the number of log lines:
    # after the first 12 executions, probes only emit on powers of two.
    for pc, hit in ENTRY.findall(content):
        counts[pc] = max(counts.get(pc, 0), int(hit))
    for pc, hit in SINGLE.findall(content):
        single[pc] = max(single.get(pc, 0), int(hit))
    return Sample(
        total_lines=content.count("\n"),
        unique_decoder_pcs=len(counts),
        max_hit_by_pc=counts,
        single_hits=single,
    )


def report(short: Sample, long: Sample, short_seconds: int,
           long_seconds: int) -> str:
    if short_seconds <= 0 or long_seconds <= short_seconds:
        raise ValueError("Require a positive short and longer comparison window")
    lines = [
        "Reflex original resource-decoder runtime duration comparison",
        f"Control: {short_seconds}s; extended: {long_seconds}s",
        "Counters are independent per translated PC; values are lower bounds.",
        "Both runs must use the same traced binary and environment.",
        f"Control decoder: {short.unique_decoder_pcs} observed PC sites",
        f"Extended decoder: {long.unique_decoder_pcs} observed PC sites",
    ]
    progressed = False
    paired = False
    for pc in MARKERS:
        a, b = (short.max_hit_by_pc.get(pc, 0),
                long.max_hit_by_pc.get(pc, 0))
        lines.append(f"PC {pc}: control_hits>={a} extended_hits>={b}")
        if a and b:
            paired = True
        if b > a:
            progressed = True
    for pc in RETURNED:
        # Return is logged by different instrumentation groups.
        a = max(short.max_hit_by_pc.get(pc, 0),
                short.single_hits.get(pc, 0))
        b = max(long.max_hit_by_pc.get(pc, 0),
                long.single_hits.get(pc, 0))
        lines.append(f"Return/status PC {pc}: control={a} extended={b}")
        if b > a:
            progressed = True
    if long.unique_decoder_pcs > short.unique_decoder_pcs:
        progressed = True
    if not paired:
        outcome = "INCONCLUSIVE - tracked parser loop not observed in both runs"
    elif progressed:
        outcome = "ADVANCED - extended run reached additional checkpoints"
    else:
        outcome = "NO MEASURABLE ADVANCE - longer wall time did not increase sampled loop progress"
    lines.append("Observation: " + outcome)
    lines.append(
        "A running process, a green CI job, or a higher PC address is not "
        "proof of successful game boot."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("control_log", type=Path)
    ap.add_argument("extended_log", type=Path)
    ap.add_argument("--control-seconds", type=int, default=15)
    ap.add_argument("--extended-seconds", type=int, default=60)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    output = report(
        sample(args.control_log.read_text(errors="replace")),
        sample(args.extended_log.read_text(errors="replace")),
        args.control_seconds,
        args.extended_seconds,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
