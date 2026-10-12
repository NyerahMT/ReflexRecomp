#!/usr/bin/env python3
"""Assess long native MXTables loading without claiming that survival is gameplay.

The objective of a bounded extended run is to see whether the original nested
decoder returns and its original loader marks the resource complete.
Use the exact guest-PC trace markers already emitted by the existing runtime.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from profile_reflex_decoder import sample

KEY = ("004eefa0", "004ef3c1", "004ef52e", "004ef58a", "004ef73e",
       "004f019e", "0084bf12", "0084bfb8")


def report(reference: str, extended: str, seconds: int) -> str:
    if seconds < 1:
        raise ValueError("Duration must be positive")
    a = sample(reference)
    b = sample(extended)
    lines = [
        f"Original Reflex MXTables loading: extended {seconds}-second qualification",
        "Counters are lower bounds on real guest-PC execution.",
        "A process timeout is not a game startup success.",
    ]
    for pc in KEY:
        first = max(a.max_hit_by_pc.get(pc, 0), a.single_hits.get(pc, 0))
        second = max(b.max_hit_by_pc.get(pc, 0), b.single_hits.get(pc, 0))
        lines.append(
            f"Guest PC {pc}: reference_60s>={first} extended>={second}"
        )
    callback = b.max_hit_by_pc.get("004f019e", 0) > 0
    resource = (
        b.max_hit_by_pc.get("0084bf12", 0) > 0 or
        b.single_hits.get("0084bf12", 0) > 0 or
        b.single_hits.get("0084bfb8", 0) > 0
    )
    lines.extend([
        f"Nested decoder returned to caller: {callback}",
        f"Original type-1 resource loader returned/completed: {resource}",
        "Status: " + (
            "LOADER RETURN OBSERVED (verify menu separately)" if resource else
            "DECODER RETURN OBSERVED (loader still unverified)" if callback else
            "NO DECODE RETURN OBSERVED"
        ),
    ])
    if b.max_hit_by_pc.get("004ef52e", 0) > a.max_hit_by_pc.get("004ef52e", 0):
        lines.append("The MXTables decoder progressed beyond the 60s control.")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", type=Path)
    ap.add_argument("extended", type=Path)
    ap.add_argument("--seconds", type=int, default=840)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    result = report(
        args.reference.read_text(errors="replace"),
        args.extended.read_text(errors="replace"),
        args.seconds,
    )
    print(result, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)


if __name__ == "__main__":
    main()
