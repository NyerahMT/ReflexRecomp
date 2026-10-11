#!/usr/bin/env python3
"""Validate the exact original Reflex DX9 startup databases in private iOS CI.

This checks only file presence and sizes. Never print, upload or embed private
game resource bytes into a public ReflexRecomp diagnostic artifact.
"""
import argparse
from pathlib import Path

REQUIRED = (
    "MXUI.dx9.database",
    "MXUI.dx9.package",
    "EngineDependencies.dx9.package",
)


def audit(root: Path, label: str) -> dict[str, int]:
    db = root / "Database"
    measured = {}
    for name in REQUIRED:
        source = db / name
        if not source.is_file() or source.stat().st_size < 1:
            raise ValueError(f"{label}: missing or empty Database/{name}")
        measured[name] = source.stat().st_size
    return measured


def verify(game_root: Path, app: Path | None = None) -> list[str]:
    sources = audit(game_root, "private original game")
    messages = [
        f"private game: {len(sources)}/{len(REQUIRED)} required database assets",
    ]
    if app is not None:
        if not app.is_dir() or not (app / "Info.plist").is_file():
            raise ValueError("built iPhone .app bundle missing or incomplete")
        bundled = audit(app / "game", "iPhone app")
        for name, size in sources.items():
            if bundled[name] != size:
                raise ValueError(
                    f"iPhone app: Database/{name} size mismatch; "
                    f"original={size}B bundled={bundled[name]}B"
                )
        messages.append(
            f"iPhone app: {len(bundled)}/{len(REQUIRED)} original "
            "startup database assets present and size-verified"
        )
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--app", type=Path)
    args = parser.parse_args()
    for message in verify(args.game_root, args.app):
        print(message)


if __name__ == "__main__":
    main()
