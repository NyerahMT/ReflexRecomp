#!/usr/bin/env python3
"""Count grounded renderer evidence; absent markers are unknown, not zero."""
from pathlib import Path
import argparse
import re

DRAW = re.compile(r"d3d9: draw (\d+):")
PRESENT = re.compile(r"\[reflex-frame\] present n=(\d+)")
SKIP = re.compile(r"\[reflex-frame\] shaderless-skip n=(\d+) fvf=([0-9a-fA-F]+)")
RGB = re.compile(r"\[reflex-frame\] rgb n=(\d+) size=(\d+)x(\d+) sampled=(\d+) lit=(\d+) hash=([a-fA-F0-9]+)")

def measure(log):
    data = {"last_draw": None, "presents": None, "shaderless_skips": None,
            "last_fvf": None, "rgb": None}
    for line in log.splitlines():
        if m := DRAW.search(line):
            data["last_draw"] = max(data["last_draw"] or 0, int(m[1]))
        if m := PRESENT.search(line):
            data["presents"] = max(data["presents"] or 0, int(m[1]))
        if m := SKIP.search(line):
            data["shaderless_skips"] = max(data["shaderless_skips"] or 0, int(m[1]))
            data["last_fvf"] = m[2].lower()
        if m := RGB.search(line):
            data["rgb"] = {"present": int(m[1]), "size": f"{m[2]}x{m[3]}",
                           "samples": int(m[4]), "lit": int(m[5]), "hash": m[6].lower()}
    return data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    result = measure(parser.parse_args().log.read_text(errors="replace"))
    print("D3D9 runtime frame frontier (None = not observed/instrumented):")
    for key, value in result.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    main()
