#!/usr/bin/env python3
"""Classify a single original Reflex draw's isolated GPU A/B replay.

No private assets or shader binaries are read. The classifier consumes only
aggregate counters logged by the opt-in, bounded on-device experiment.
"""
import argparse
import json
from pathlib import Path
import re

PREFIX = "[reflex-gpu-ab] od=8 "
FIELDS = (
    "read_original", "read_blend", "read_direct",
    "direct_rgb", "direct_alpha", "blend_rgb", "original_rgb",
    "direct_nonzero", "original_nonzero",
    "active", "within2", "max_blend_error", "max_original_error",
    "shader_alpha_low", "shader_alpha_high", "depth_detached",
)


def classify(log_text: str) -> dict:
    matches = [line for line in log_text.splitlines() if PREFIX in line]
    if not matches:
        return {"status": "no_capture", "confidence": "none",
                "reason": "Original draw #8 A/B readback was not recorded"}
    line = matches[-1].split(PREFIX, 1)[1]
    vals = {key: int(value) for key, value in
            re.findall(r"(\w+)=(\d+)", line)}
    missing = [f for f in FIELDS if f not in vals]
    if missing:
        return {"status": "malformed_capture", "confidence": "none",
                "reason": f"Missing fields: {', '.join(missing)}"}
    if vals["read_original"] != 1 or vals["read_blend"] != 1 or vals["read_direct"] != 1:
        status, why = "readback_failed", "At least one GPU readback did not complete"
        confidence = "none"
    elif vals["active"] == 0:
        status, why = "inconclusive_no_coverage", "No non-black fragment output in sampled pixels"
        confidence = "none"
    elif vals["max_original_error"] > 2:
        status, why = "replay_not_equivalent", (
            "The baseline scratch draw diverged from the original target; "
            "a detached depth buffer or other target dependency may explain this")
        confidence = "low"
    elif vals["max_blend_error"] > 2:
        status, why = "blend_math_mismatch", (
            "Same-coordinate GPU blended RGB deviates from decoded "
            "SRCALPHA over black reference by more than 2 UNORM levels")
        confidence = "high"
    elif vals["direct_rgb"] <= 15:
        status, why = "fragment_output_dark", (
            "Unblended pixel shader output is already at or below 15/255")
        confidence = "high"
    elif vals["blend_rgb"] <= 15:
        status, why = "alpha_attenuation_consistent", (
            "Unblended shader RGB exceeds 15; original blending reproduces "
            "the dim result and agrees with SRCALPHA math")
        confidence = "high"
    else:
        status, why = "other_pipeline_issue", (
            "The scratch draw is bright but original output still needs "
            "per-stage investigation")
        confidence = "medium"
    return {"status": status, "confidence": confidence,
            "reason": why, "metrics": {f: vals[f] for f in FIELDS}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = classify(args.log.read_text(errors="replace"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Original Reflex draw #8 GPU A/B: {result['status']} "
          f"(confidence: {result['confidence']})")
    print(result["reason"])
    if "metrics" in result:
        m = result["metrics"]
        print(f"Shader RGB/alpha peaks={m['direct_rgb']}/{m['direct_alpha']}, "
              f"isolated blend RGB={m['blend_rgb']}, "
              f"actual original RGB={m['original_rgb']}; "
              f"blend-model max error={m['max_blend_error']}, "
              f"scratch-vs-original max error={m['max_original_error']}")
    if result["status"] in ("no_capture", "malformed_capture", "readback_failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
