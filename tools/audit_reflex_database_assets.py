#!/usr/bin/env python3
"""Inventory original Reflex DX9 Database packages across private ZIPs.

Only filenames and counts are reported; original archive data stays on the
private CI runner. Exact original bytes are staged atomically; no placeholders.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

EXTENSIONS = (".dx9.package", ".dx9.database")
MAX_ASSET_BYTES = 3 * 1024 ** 3


def valid_name(info: zipfile.ZipInfo) -> str | None:
    if info.is_dir():
        return None
    raw = info.filename.replace("\\", "/")
    p = PurePosixPath(raw)
    if p.is_absolute() or ".." in p.parts:
        return None
    name = p.name
    if not name or not name.casefold().endswith(EXTENSIONS):
        return None
    # Flat archive records or paths beneath the Database folder are allowed.
    # Never promote other paths or archive metadata into the game Database.
    parents = [part.casefold() for part in p.parts[:-1]]
    if parents and "database" not in parents and len(p.parts) > 1:
        return None
    return name


def inventory(archives: list[Path], root: Path, *, stage: bool,
              max_stage_bytes: int, reserve_bytes: int) -> dict:
    assets: dict[str, list[tuple[Path, zipfile.ZipInfo, str]]] = defaultdict(list)
    for archive in archives:
        if not archive.is_file():
            raise FileNotFoundError(archive)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = valid_name(info)
                if name:
                    assets[name.casefold()].append((archive, info, name))
    db = root / "Database"
    present, missing, collisions, invalid, staged, budget_skipped = [], [], [], [], [], []
    bytes_copied = 0
    names = sorted(assets)
    for key in names:
        options = assets[key]
        fingerprints = {(i.file_size, i.CRC) for _, i, _ in options}
        if len(fingerprints) > 1:
            collisions.append(key)
            continue
        archive, info, filename = options[0]
        target = db / filename
        if target.is_file() and target.stat().st_size == info.file_size and info.file_size > 0:
            present.append(key)
            continue
        # An existing file that does not match the archived copy is not
        # overwritten automatically. Require explicit investigation.
        if target.exists():
            collisions.append(key)
            continue
        missing.append(key)
        if not stage:
            continue
        if info.file_size <= 0 or info.file_size > MAX_ASSET_BYTES:
            invalid.append(key)
            continue
        free = shutil.disk_usage(db if db.exists() else root).free
        if (bytes_copied + info.file_size > max_stage_bytes or
                free - info.file_size < reserve_bytes):
            budget_skipped.append(key)
            continue
        db.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=db, prefix=".reflex-db-",
                                             delete=False) as output:
                tmp = Path(output.name)
                with zipfile.ZipFile(archive) as z, z.open(info) as source:
                    shutil.copyfileobj(source, output, length=1 << 20)
            if tmp.stat().st_size != info.file_size:
                raise ValueError("Private asset extraction size mismatch")
            os.replace(tmp, target)
            bytes_copied += info.file_size
            staged.append(key)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return {
        "scope": "Only *.dx9.package and *.dx9.database in the four private game ZIP archives",
        "source_archives": len(archives),
        "original_asset_names": len(names),
        "already_present_matching_size": len(present),
        "missing_before": len(missing),
        "newly_staged": len(staged),
        "missing_after": len(missing) - len(staged),
        "conflicting_original_entries_or_existing_files": len(collisions),
        "invalid_empty_or_oversized": len(invalid),
        "skipped_due_to_disk_budget": len(budget_skipped),
        "bytes_staged": bytes_copied,
        "stage_enabled": stage,
        "complete": not (len(missing) - len(staged) or collisions),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, action="append", required=True)
    p.add_argument("--game-root", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--stage", action="store_true")
    p.add_argument("--max-stage-bytes", type=int, default=2 * 1024 ** 3)
    p.add_argument("--reserve-bytes", type=int, default=4 * 1024 ** 3)
    a = p.parse_args()
    if a.max_stage_bytes < 0 or a.reserve_bytes < 0:
        p.error("Disk budgets cannot be negative")
    result = inventory(a.archive, a.game_root, stage=a.stage,
                       max_stage_bytes=a.max_stage_bytes, reserve_bytes=a.reserve_bytes)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2) + "\n")
    print("Reflex original Database asset inventory:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
