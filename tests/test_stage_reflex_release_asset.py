"""No proprietary payload needed: validate exact private ZIP extraction policy."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stage_reflex_release_asset", ROOT / "tools" / "stage_reflex_release_asset.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)


def test_extract_single_nested_original_filename(tmp_path):
    archive = tmp_path / "Archive.2.zip"
    output = tmp_path / "Database" / "Music.dx9.package"
    make_zip(archive, [("other/file.txt", b"not the game"),
                       ("game/Database/Music.dx9.package", b"real-example-content")])
    assert mod.extract(archive, "Music.dx9.package", output)
    assert output.read_bytes() == b"real-example-content"
    assert not mod.extract(archive, "NotThere.package",
                           tmp_path / "NotThere.package")


def test_rejects_duplicate_or_empty_private_assets_without_overwriting(tmp_path):
    archive = tmp_path / "Archive.3.zip"
    dest = tmp_path / "Music.dx9.package"
    dest.write_bytes(b"preserve-this")
    make_zip(archive, [("one/Music.dx9.package", b"one"),
                       ("two/Music.dx9.package", b"two")])
    with pytest.raises(ValueError, match="Ambiguous"):
        mod.extract(archive, dest.name, dest)
    assert dest.read_bytes() == b"preserve-this"
    make_zip(archive, [("Music.dx9.package", b"")])
    with pytest.raises(ValueError, match="empty"):
        mod.extract(archive, dest.name, dest)
    assert dest.read_bytes() == b"preserve-this"


def test_rejects_unsafe_output_and_archive_paths(tmp_path):
    archive = tmp_path / "Archive.zip"
    make_zip(archive, [("../Music.dx9.package", b"payload")])
    with pytest.raises(ValueError, match="Unsafe"):
        mod.extract(archive, "Music.dx9.package",
                    tmp_path / "Music.dx9.package")
    with pytest.raises(ValueError, match="single filename"):
        mod.extract(archive, "../Music.dx9.package",
                    tmp_path / "Music.dx9.package")
    with pytest.raises(ValueError, match="Output basename"):
        mod.extract(archive, "Music.dx9.package", tmp_path / "Different.file")


def test_workflow_requires_original_asset_before_game_launch():
    workflow = (ROOT / ".github" / "workflows" / "fast-iterate.yml").read_text()
    assert workflow.index("tools/stage_reflex_release_asset.py") < workflow.index(
        "      - name: Locate and verify private executable")
    assert "Original Database/Music.dx9.package missing" in workflow
    assert "--name Music.dx9.package" in workflow
    assert '"$status" -ne 3' in workflow
    assert "Archive.2.zip Archive.zip" in workflow
