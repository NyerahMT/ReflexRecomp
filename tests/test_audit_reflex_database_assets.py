"""Synthetic, asset-free tests for bounded original Database inventory."""
import importlib.util
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "audit_reflex_database_assets", ROOT / "tools" / "audit_reflex_database_assets.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def pack(path, content):
    with zipfile.ZipFile(path, "w") as z:
        for name, value in content:
            z.writestr(name, value)


def test_inventory_and_batch_stage_without_replacing_good_originals(tmp_path):
    game = tmp_path / "game"
    db = game / "Database"
    db.mkdir(parents=True)
    (db / "Existing.dx9.package").write_bytes(b"OK")
    a = tmp_path / "Archive.zip"
    b = tmp_path / "Archive.3.zip"
    pack(a, [("Database/Existing.dx9.package", b"OK"),
             ("Database/Music.dx9.package", b"sound"),
             ("Database/Intro.dx9.database", b"index"),
             ("Textures/Bad.dx9.package", b"not a database asset"),
             ("Database/readme.txt", b"skip")])
    pack(b, [("CrowdSoundProjects.dx9.package", b"crowds"),
             ("Database/Music.dx9.package", b"sound")])
    audit = mod.inventory([a, b], game, stage=False,
                          max_stage_bytes=100, reserve_bytes=0)
    assert audit["original_asset_names"] == 4
    assert audit["missing_before"] == 3
    assert audit["newly_staged"] == 0
    staged = mod.inventory([a, b], game, stage=True,
                           max_stage_bytes=100, reserve_bytes=0)
    assert staged["newly_staged"] == 3
    assert staged["missing_after"] == 0
    assert staged["complete"]
    assert (db / "Music.dx9.package").read_bytes() == b"sound"
    assert (db / "CrowdSoundProjects.dx9.package").read_bytes() == b"crowds"
    assert (db / "Intro.dx9.database").read_bytes() == b"index"
    assert (db / "Existing.dx9.package").read_bytes() == b"OK"
    assert not (db / "Bad.dx9.package").exists()


def test_inventory_reports_conflict_without_guessing(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    a, b = tmp_path / "Archive.2.zip", tmp_path / "Archive.4.zip"
    pack(a, [("Database/Audio.dx9.package", b"one")])
    pack(b, [("Database/Audio.dx9.package", b"different")])
    res = mod.inventory([a, b], root, stage=True,
                        max_stage_bytes=100, reserve_bytes=0)
    assert res["conflicting_original_entries_or_existing_files"] == 1
    assert not res["complete"]
    assert not (root / "Database" / "Audio.dx9.package").exists()


def test_inventory_reports_disk_limit(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    archive = tmp_path / "Archive.zip"
    pack(archive, [("Database/Big.dx9.package", b"12345678"),
                   ("Database/Small.dx9.package", b"abcd")])
    res = mod.inventory([archive], root, stage=True,
                        max_stage_bytes=5, reserve_bytes=0)
    assert res["original_asset_names"] == 2
    assert res["newly_staged"] == 1
    assert res["missing_after"] == 1
    assert res["skipped_due_to_disk_budget"] == 1
    assert not res["complete"]


def test_inventory_ignores_unsafe_zip_entries(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    archive = tmp_path / "Archive.zip"
    pack(archive, [("../Database/Bad.dx9.package", b"skip"),
                   ("/Database/Bad2.dx9.package", b"skip"),
                   ("__MACOSX/Bad3.dx9.package", b"skip"),
                   ("Database/Good.dx9.package", b"yes")])
    res = mod.inventory([archive], root, stage=True,
                        max_stage_bytes=100, reserve_bytes=0)
    assert res["original_asset_names"] == 1
    assert (root / "Database" / "Good.dx9.package").read_bytes() == b"yes"


def test_workflow_lists_every_private_archive_before_cleanup():
    text = (ROOT / ".github" / "workflows" / "fast-iterate.yml").read_text()
    assert "tools/audit_reflex_database_assets.py" in text
    assert text.index("tools/audit_reflex_database_assets.py") < text.index(
        'rm -f "$RUNNER_TEMP/reflex-assets/Archive.3.zip"')
    assert "--max-stage-bytes" in text
    assert "Archive.2.zip" in text
