#!/usr/bin/env python3
"""Replace one cached translated function with a freshly generated copy.

The baseline remains private. This script sees only generated C on the runner
and writes it back into the runner's extracted cache; no recovered source is
committed or uploaded by this repository.
"""

import argparse
from pathlib import Path
import re


def block_pattern(addr: str) -> re.Pattern[str]:
    # A generated function begins with:
    #   /* NAME  N insns  AAAAAAAA..BBBBBBBB... */
    return re.compile(
        r"/\*[^\n]*\b" + re.escape(addr) + r"\.\.[^\n]*\*/\n"
    )


def find_block(path: Path, addr: str):
    text = path.read_text()
    match = block_pattern(addr).search(text)
    if not match:
        return None
    start = match.start()
    next_comment = text.find("\n/* ", match.end())
    end = len(text) if next_comment < 0 else next_comment + 1
    return text, start, end


def locate(root: Path, addr: str):
    hits = []
    for path in sorted(root.glob("chunk_*.c")):
        found = find_block(path, addr)
        if found:
            hits.append((path, found))
    if len(hits) != 1:
        raise SystemExit(f"expected one generated block for {addr} under {root}, found {len(hits)}")
    return hits[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", type=Path, required=True)
    ap.add_argument("--fresh", type=Path, required=True)
    ap.add_argument("--address", required=True)
    args = ap.parse_args()

    addr = args.address.lower().removeprefix("0x").zfill(8)
    fresh_path, (fresh_text, fresh_start, fresh_end) = locate(args.fresh, addr)
    cached_path, (cached_text, cached_start, cached_end) = locate(args.cached, addr)

    replacement = fresh_text[fresh_start:fresh_end]
    cached_path.write_text(cached_text[:cached_start] + replacement + cached_text[cached_end:])
    print(f"Refreshed fn_{addr} in {cached_path.name} from {fresh_path.name}")


if __name__ == "__main__":
    main()
