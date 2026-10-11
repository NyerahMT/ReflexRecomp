"""Regression tests for validating private startup assets in an iPhone bundle."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/verify_ios_reflex_assets.py"
spec = importlib.util.spec_from_file_location("ios_asset_check", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fill(root: Path, sizes=(5, 6, 7)):
    db = root / "Database"
    db.mkdir(parents=True)
    for name, size in zip(mod.REQUIRED, sizes):
        (db / name).write_bytes(b"x" * size)


def test_exact_asset_manifest_matches_bundle(tmp_path):
    game = tmp_path / "retail"
    app = tmp_path / "ReflexRecomp.app"
    app.mkdir()
    (app / "Info.plist").write_text("placeholder")
    fill(game)
    fill(app / "game")
    result = mod.verify(game, app)
    assert "3/3 required database assets" in result[0]
    assert "3/3 original startup database assets" in result[1]


def test_missing_private_archive_file_fails(tmp_path):
    game = tmp_path / "game"
    fill(game)
    (game / "Database" / mod.REQUIRED[1]).unlink()
    with pytest.raises(ValueError, match="Database/MXUI.dx9.package"):
        mod.verify(game)


def test_missing_bundled_file_fails(tmp_path):
    game = tmp_path / "game"
    app = tmp_path / "ReflexRecomp.app"
    app.mkdir()
    (app / "Info.plist").write_text("placeholder")
    fill(game)
    fill(app / "game")
    (app / "game" / "Database" / mod.REQUIRED[2]).unlink()
    with pytest.raises(ValueError, match="EngineDependencies.dx9.package"):
        mod.verify(game, app)


def test_asset_size_mismatch_fails(tmp_path):
    game = tmp_path / "game"
    app = tmp_path / "ReflexRecomp.app"
    app.mkdir()
    (app / "Info.plist").write_text("placeholder")
    fill(game)
    fill(app / "game", sizes=(5, 99, 7))
    with pytest.raises(ValueError, match="size mismatch"):
        mod.verify(game, app)
