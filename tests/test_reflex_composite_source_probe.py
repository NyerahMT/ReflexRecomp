"""Pinned source regression: compare GPU FFP input to final D3D9 framebuffer."""
import importlib.util
import shutil
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(file, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

FRAMES = load("patch_reflex_frame_probe.py", "frame_composite")
COMPARE = load("patch_reflex_composite_source_probe.py", "composite_source")

def test_composite_real_frame_patch_order_and_idempotence(tmp_path):
    original = ROOT / "kit" / "dx" / "d3d9.cpp"
    if not original.is_file():
        pytest.skip("Pinned recomp-kit source is present in CI")
    kit = tmp_path / "kit"
    target = kit / "dx" / "d3d9.cpp"
    target.parent.mkdir(parents=True)
    shutil.copyfile(original, target)
    FRAMES.patch_frame_probe(kit, ROOT / "runtime")
    COMPARE.patch_composite_source_probe(kit)
    actual = target.read_text()
    assert actual.count(COMPARE.MARKER) == 1
    assert actual.count("[reflex-composite] source") == 1
    assert actual.count("[reflex-composite] texpixels") == 1
    assert "host_d9_texture_read(tex->id, 0u, 0u" in actual
    assert "tex->rmask == 21u || tex->rmask == 22u" in actual
    assert "REFLEX_COMPOSITE_PROBE" in actual
    assert "n == 8192u" in actual
    assert "host_d9_read_presented(" in actual
    COMPARE.patch_composite_source_probe(kit)
    FRAMES.patch_frame_probe(kit, ROOT / "runtime")
    assert target.read_text() == actual

def test_composite_source_probe_fails_closed_on_layout_changes(tmp_path):
    kit = tmp_path / "kit"
    target = kit / "dx" / "d3d9.cpp"
    target.parent.mkdir(parents=True)
    broken = COMPARE.BEFORE.replace(
        "host_d9_present(bb->id, bb->width, bb->height);",
        "host_d9_present(bb->id, bb->height, bb->width);")
    target.write_text(broken)
    with pytest.raises(RuntimeError, match="post-present frame-probe"):
        COMPARE.patch_composite_source_probe(kit)
    assert target.read_text() == broken

def test_composite_diagnostic_never_edits_original_state(tmp_path):
    kit = tmp_path / "kit"
    p = kit / "dx" / "d3d9.cpp"
    p.parent.mkdir(parents=True)
    p.write_text(COMPARE.BEFORE)
    COMPARE.patch_composite_source_probe(kit)
    transformed = p.read_text()
    assert COMPARE.MARKER in transformed
    assert "const int ok = host_d9_texture_read" in transformed
    assert "LOGW(" in transformed
    assert "host_d9_present(bb->id, bb->width, bb->height);" in transformed
    assert "host_d9_draw" not in transformed
    assert "memcpy" not in transformed
    assert "REFLEX_COMPOSITE_PROBE" in transformed
