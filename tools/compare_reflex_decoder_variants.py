#!/usr/bin/env python3
"""Compare same-duration Reflex decoder progress with two Mesa worker settings.

The original guest parser loops while Mesa llvmpipe software rendering uses
roughly a CPU core. Mesa allows LP_NUM_THREADS to limit rasterizer workers.
Both runs must use the same binary, assets, probes, and time window; the
renderer worker count is the only intended difference.

A single comparison is evidence, not proof of a game behavior correction.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from profile_reflex_decoder import MARKERS, RETURNED, Sample, sample


def report_variant(baseline: Sample, variant: Sample, seconds: int) -> str:
    if seconds <= 0:
        raise ValueError("Comparison window must be positive")
    lines = [
        "Reflex MXTables decoder: Mesa software rendering worker A/B",
        f"Both durations: {seconds}s; baseline=default Mesa; variant=LP_NUM_THREADS=1",
        "Counters are lower bounds because probes sample hits exponentially.",
        "Only software rasterizer thread-count differs between runs.",
    ]
    advanced = False
    observed = False
    for pc in MARKERS:
        a, b = baseline.max_hit_by_pc.get(pc, 0), variant.max_hit_by_pc.get(pc, 0)
        if a and b:
            observed = True
        if b > a:
            advanced = True
        lines.append(
            f"PC {pc}: baseline>={a} lp1>={b} "
            f"trend={'up' if b > a else ('down' if b < a else 'equal')}"
        )
    for pc in RETURNED:
        a = max(baseline.max_hit_by_pc.get(pc, 0),
                baseline.single_hits.get(pc, 0))
        b = max(variant.max_hit_by_pc.get(pc, 0),
                variant.single_hits.get(pc, 0))
        lines.append(f"Guest return/status {pc}: baseline={a} lp1={b}")
        if b > a:
            advanced = True
    if not observed:
        outcome = "INCONCLUSIVE - no common decoder heartbeat reached"
    elif advanced:
        outcome = "VARIANT REACHED MORE CHECKPOINTS"
    else:
        outcome = "NO MEASURED GAIN FROM ONE MESA WORKER"
    lines.append("Observation: " + outcome)
    lines.append("A green CI job or timeout exit is NOT proof of successful game boot.")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("baseline_log", type=Path)
    p.add_argument("variant_log", type=Path)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = report_variant(
        sample(args.baseline_log.read_text(errors="replace")),
        sample(args.variant_log.read_text(errors="replace")),
        args.seconds,
    )
    print(result, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)


if __name__ == "__main__":
    main()
