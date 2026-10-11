"""Read-only, fail-closed probe for Reflex's original blocked initializer."""
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/patch_reflex_cached_first_loader.py"
spec = importlib.util.spec_from_file_location("first_loader", SCRIPT)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def make_chunks(base: Path, omit=(), duplicate=()):
    base.mkdir(parents=True)
    for index in range(2):
        subset = list(patch.STAGES[:9] if index == 0 else patch.STAGES[9:])
        subset = [s for s in subset if s not in omit] + [s for s in duplicate if s in subset]
        body = (
            "#include <stdint.h>\n"
            "static void body_004e6c30(X86 *c, uint32_t entry_) {\n"
            + "".join(f"    fake_call(); /* {pc} CALL */\n" for pc in subset)
            + "}\n"
        )
        (base / f"chunk_{index:02d}.c").write_text(body)


def test_probe_finds_all_original_instructions_across_chunks(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen)
    patched = patch.patch_stages(gen)
    assert len(patched) == 2
    for file in patched:
        source = file.read_text()
        assert source.count("fake_call();") > 0
        assert source.count(patch.MARKER) == source.count("[reflex-first-loader]")
        assert "c->r[4]" in source
    assert patch.patch_stages(gen) == patched  # idempotent
    for file in patched:
        assert file.read_text().count(patch.MARKER) > 0


def test_probe_is_strict_about_missing_or_duplicate_critical_sites(tmp_path):
    a = tmp_path / "missing"
    make_chunks(a, omit={"004e6c48"})
    before = (a / "chunk_00.c").read_text()
    with pytest.raises(RuntimeError, match="checkpoints"):
        patch.patch_stages(a)
    assert (a / "chunk_00.c").read_text() == before

    b = tmp_path / "duplicate"
    make_chunks(b, duplicate={"004e6c91"})
    with pytest.raises(RuntimeError, match="checkpoints"):
        patch.patch_stages(b)


def test_no_generated_translation_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="No translated chunks"):
        patch.patch_stages(tmp_path)


def test_original_executable_stage_locations():
    assert patch.STAGES[0] == "004e6c48"
    assert patch.STAGES[-1] == "004e6f40"
    assert "004e6d37" in patch.STAGES
