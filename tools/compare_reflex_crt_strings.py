#!/usr/bin/env python3
"""Compare original CRT guest-string path to opt-in allocation-free path.

Both runs must use the identical game binary, assets, host renderer settings,
checkpoint instrumentation, and duration. Reading logs is diagnostic only.
"""
from __future__ import annotations
import argparse
from pathlib import Path

from profile_reflex_decoder import sample, MARKERS, RETURNED


def report(baseline_log: str, fast_log: str, seconds: int) -> str:
    if seconds <= 0:
        raise ValueError("Both observation windows must be positive")
    baseline = sample(baseline_log)
    candidate = sample(fast_log)
    active = "[reflex-crt-fast] enabled=1" in fast_log
    lines = [
        f"Reflex MXTables original vs allocation-free CRT strings ({seconds}s each)",
        f"Opt-in fast CRT initialization observed: {active}",
        "Both runs use the same native game executable, input and graphic settings.",
        "Counters show lower bounds; no decoded-record total is inferred.",
    ]
    shared = False
    increased = False
    for pc in MARKERS:
        a = baseline.max_hit_by_pc.get(pc, 0)
        b = candidate.max_hit_by_pc.get(pc, 0)
        lines.append(f"PC {pc}: reference>={a} optimized>={b}")
        shared |= a > 0 and b > 0
        increased |= b > a
    for pc in RETURNED:
        a = max(baseline.max_hit_by_pc.get(pc, 0), baseline.single_hits.get(pc, 0))
        b = max(candidate.max_hit_by_pc.get(pc, 0), candidate.single_hits.get(pc, 0))
        lines.append(f"Resource return/status {pc}: reference={a} optimized={b}")
        increased |= b > a
    lines.append("Observation: " + (
        "INCONCLUSIVE - fast CRT never initialized"
        if not active else
        "INCONCLUSIVE - decoder checkpoints missing in one run"
        if not shared else
        "OPTIMIZED REACHED MORE SAMPLED CHECKPOINTS" if increased else
        "NO MEASURABLE THROUGHPUT GAIN"
    ))
    lines.append("Repeated samples and guest readiness are required before enabling by default.")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("reference_log", type=Path)
    p.add_argument("optimized_log", type=Path)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = report(args.reference_log.read_text(errors="replace"),
                    args.optimized_log.read_text(errors="replace"),
                    args.seconds)
    print(result, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)


if __name__ == "__main__":
    main()
