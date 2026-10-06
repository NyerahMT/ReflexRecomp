#!/usr/bin/env python3
"""Print a tiny private-listing context around one or more guest addresses."""

from pathlib import Path
import argparse
import csv
import re

LINE_RE = re.compile(r"^([0-9A-Fa-f]{8})\s{2}(.*)$")


def load_names(root: Path):
    names = {}
    index = root / "functions.tsv"
    if not index.is_file():
        return names
    with index.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                names[int(row["address"], 16)] = row["name"]
            except Exception:
                pass
    return names


def parse_asm(path: Path):
    rows = []
    for raw in path.read_text(errors="replace").splitlines():
        m = LINE_RE.match(raw)
        if m:
            rows.append((int(m.group(1), 16), raw))
    return rows


def context_for(root: Path, target: int, names):
    funcs = root / "functions"
    exact = None
    containing = None
    for path in funcs.glob("*.asm"):
        rows = parse_asm(path)
        if not rows:
            continue
        addrs = [a for a, _ in rows]
        if target in addrs:
            exact = (path, rows)
            break
        if min(addrs) <= target <= max(addrs):
            containing = (path, rows)

    found = exact or containing
    print(f"target=0x{target:08x}")
    if not found:
        print("  function=not-found")
        return

    path, rows = found
    try:
        start = int(path.stem, 16)
    except ValueError:
        start = rows[0][0]
    print(f"  function=0x{start:08x} {names.get(start, '')}".rstrip())

    nearest = min(range(len(rows)), key=lambda i: abs(rows[i][0] - target))
    lo = max(0, nearest - 5)
    hi = min(len(rows), nearest + 5)
    for i in range(lo, hi):
        mark = ">" if i == nearest else " "
        print(f"  {mark} {rows[i][1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing_root", type=Path)
    ap.add_argument("addresses", nargs="+")
    args = ap.parse_args()

    names = load_names(args.listing_root)
    for raw in args.addresses:
        target = int(raw.lower().removeprefix("0x"), 16)
        context_for(args.listing_root, target, names)


if __name__ == "__main__":
    main()
