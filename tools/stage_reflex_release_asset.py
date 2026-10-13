#!/usr/bin/env python3
"""Locate one original Reflex asset inside a private GitHub release ZIP.

No proprietary payload or archive listing is emitted. A missing entry returns
exit code 3 so CI can try the next source archive; corrupt/ambiguous entries
fail closed rather than producing an empty placeholder.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

MAX_BYTES = 8 * (1024 ** 3)


def extract(archive: Path, basename: str, destination: Path) -> bool:
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if not basename or Path(basename).name != basename or "\\" in basename:
        raise ValueError("Expected a single filename, not an archive path")
    if destination.name.lower() != basename.lower():
        raise ValueError("Output basename does not match required asset")

    with zipfile.ZipFile(archive) as z:
        matches = []
        for info in z.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.name.casefold() != basename.casefold():
                continue
            if ".." in path.parts or path.is_absolute():
                raise ValueError("Unsafe archive entry")
            matches.append(info)
        if not matches:
            return False
        if len(matches) != 1:
            raise ValueError(f"Ambiguous {basename} entries in {archive.name}")
        info = matches[0]
        if info.file_size <= 0 or info.file_size > MAX_BYTES:
            raise ValueError("Missing, empty or oversized private asset")
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=".reflex-asset-", delete=False
            ) as output:
                tmp = Path(output.name)
                with z.open(info, "r") as source:
                    shutil.copyfileobj(source, output, length=1 << 20)
            if tmp.stat().st_size != info.file_size:
                raise ValueError("Original asset has incorrect extracted size")
            os.replace(tmp, destination)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    print(f"Staged original {basename} from private {archive.name} ({info.file_size} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if extract(args.archive, args.name, args.output):
            return 0
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"{args.name} not present in {args.archive.name}")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
