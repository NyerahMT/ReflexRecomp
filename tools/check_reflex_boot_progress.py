#!/usr/bin/env python3
"""Classify Reflex's headless startup progress beyond basic process liveness.

The boot runtime gate may survive 30 seconds yet spin repeatedly looking up
the same unresolved UI asset. This check is intentionally conservative: it
only fails if the exact known Intro/Intro. hot loop exceeds a million
comparisons with multiple consistent late samples. Do not use it as a
general-purpose framerate, gameplay readiness, or rendering assertion.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
from pathlib import Path


HOT_SAMPLE = re.compile(
    r'^\[reflex-stricmp\] call=(\d+) ret=0084a8f0 '
    r'lhs=[0-9a-fA-F]+ "[^"]*" rhs=[0-9a-fA-F]+ "([^"]*)" rc=(-?\d+)',
    re.MULTILINE,
)

@dataclass(frozen=True)
class ProgressResult:
    status: str
    comparisons: int
    intro_samples: int
    reason: str


def classify_log(contents: str) -> ProgressResult:
    samples = [(int(count), key, int(result))
               for count, key, result in HOT_SAMPLE.findall(contents)]
    if not samples:
        return ProgressResult("unknown", 0, 0, "No UI lookup samples reached")
    last = samples[-8:]
    intro = sum(key in ("Intro", "Intro.") and rc != 0
                for _, key, rc in last)
    maximum = max(count for count, _, _ in samples)
    if maximum >= 1_000_000 and len(last) >= 6 and intro >= 6:
        return ProgressResult(
            "ui_lookup_stalled", maximum, intro,
            "Repeated unresolved Intro/Intro. resource lookups")
    return ProgressResult("not_stalled", maximum, intro,
                          "Known UI lookup stall signature not detected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_log", type=Path)
    args = parser.parse_args()
    result = classify_log(args.runtime_log.read_text(errors="replace"))
    print(f"Reflex startup progress: {result.status}; "
          f"lookups={result.comparisons}; "
          f"late_unresolved_intro_samples={result.intro_samples}; "
          f"reason={result.reason}")
    if result.status == "ui_lookup_stalled":
        print("FAIL: process survived but UI resource initialization is "
              "repeatedly searching for unresolved Intro keys.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
