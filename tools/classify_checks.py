#!/usr/bin/env python3
"""Decide whether a PR needs the expensive native and unsigned iOS scaffolds.

Only fast-path cached *generated guest* tracing and its focused tests are
eligible for the quicker path. Source, headers, workflow changes outside
fast-iterate, and unknown files always get full native compilation.
An empty or failed diff is conservative: rebuild.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def is_cached_diagnostic_only(path: str) -> bool:
    if path == ".github/workflows/fast-iterate.yml":
        return True
    return (
        path.startswith("tools/patch_reflex_cached_") and path.endswith(".py")
    ) or (
        path.startswith("tests/test_cached_") and path.endswith(".py")
    )


def native_required(paths: list[str]) -> bool:
    return not paths or any(not is_cached_diagnostic_only(path) for path in paths)


def changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-ext-diff", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--main", action="store_true",
                        help="Always compile on main")
    args = parser.parse_args()
    if args.main:
        required, files = True, ["main-branch build"]
    else:
        try:
            files = changed_files(args.base, args.head)
            required = native_required(files)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"WARNING: cannot classify changes ({exc}); building all", file=sys.stderr)
            files, required = ["diff unavailable"], True
    print(f"native_required={'true' if required else 'false'}")
    print(
        f"Change classification: {len(files)} file(s), "
        + ("full native/iOS scaffolds" if required else "cached diagnostic tests only"),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
