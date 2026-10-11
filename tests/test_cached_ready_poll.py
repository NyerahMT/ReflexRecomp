"""Read-only sampling of the resource-ready polling loop in original Reflex."""
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ready_poll", ROOT / "tools" / "patch_reflex_cached_ready_poll.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def chunk(dir: Path, missing: str = "", duplicate: str = "") -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    out = dir / "chunk_01.c"
    pcs = [pc for pc in probe.SITES if pc != missing]
    if duplicate:
        pcs.append(duplicate)
    out.write_text(
        "static void body_0084a7f0(X86 *c, uint32_t entry_) {\n"
        + "".join(f"    fake_op(); /* {pc} JZ 0x0084a826 */\n" for pc in pcs)
        + "}\n"
    )
    return out


def test_ready_poll_patch_preserves_game_logic(tmp_path):
    gen = tmp_path / "gen"
    out = chunk(gen)
    original = out.read_text()
    assert probe.patch_ready_poll(gen) == [out]
    patched = out.read_text()
    assert original != patched
    assert patched.count(probe.MARKER) == len(probe.SITES)
    assert patched.count("[reflex-ready-poll]") == len(probe.SITES)
    assert "fake_op();" in patched
    assert "c->r[0]" in patched
    assert "rd32(vt + 0x28u)" in patched
    assert probe.patch_ready_poll(gen) == [out]
    assert out.read_text() == patched


def test_missing_site_fails_without_modifying_generated_files(tmp_path):
    gen = tmp_path / "gen"
    out = chunk(gen, missing="0084a837")
    original = out.read_text()
    with pytest.raises(RuntimeError, match="Expected one each"):
        probe.patch_ready_poll(gen)
    assert out.read_text() == original


def test_duplicate_site_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    out = chunk(gen, duplicate="0084a81d")
    before = out.read_text()
    with pytest.raises(RuntimeError, match="Expected one each"):
        probe.patch_ready_poll(gen)
    assert before == out.read_text()


def test_partial_reinstall_is_rejected(tmp_path):
    gen = tmp_path / "gen"
    out = chunk(gen)
    probe.patch_ready_poll(gen)
    out.write_text(out.read_text().replace("[reflex-ready-poll]", "tampered", 1))
    with pytest.raises(RuntimeError, match="Partial prior patch"):
        probe.patch_ready_poll(gen)


def test_pc_sources_are_original_instruction_boundaries():
    assert probe.SITES == ("0084a81d", "0084a837", "0084a83a", "0084a873", "0084a87b")


def test_resource_lookup_vs_status_trace_coverage():
    assert "0084a873" in probe.SITES  # resource pointer from vtable+0x20
    assert "0084a87b" in probe.SITES  # resource +0x94 status result
