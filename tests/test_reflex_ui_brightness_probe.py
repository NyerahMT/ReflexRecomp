"""Real pinned-source composability for read-only Reflex UI brightness probes."""
from pathlib import Path
import importlib.util
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[1]

def script(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

PROBE = script("patch_reflex_ui_brightness_probe.py", "brightness_probe")
UPDATE = script("patch_reflex_d3d9_update_texture.py", "updated_texture")

def fixture(tmp_path):
    origin = ROOT / "kit" / PROBE.TARGET
    if not origin.is_file():
        pytest.skip("Pinned recomp-kit checkout available in CI only")
    dest = tmp_path / "kit" / PROBE.TARGET
    dest.parent.mkdir(parents=True)
    shutil.copyfile(origin, dest)
    return dest.parent.parent

def test_original_updatetexture_then_brightness_probe_and_repatch(tmp_path):
    kit = fixture(tmp_path)
    UPDATE.patch_update_texture(kit)
    PROBE.patch_brightness_probe(kit)
    path = kit / PROBE.TARGET
    output = path.read_text()
    assert output.count(PROBE.MARKER) == 1
    assert output.count("[reflex-brightness] draw") == 1
    assert output.count("[reflex-brightness] texture") == 1
    assert "REFLEX_BRIGHTNESS_PROBE" in output
    assert "n <= 8u || ((n & (n - 1u)) == 0u)" in output
    assert "gpu_after_unlock(b, 0u" in output
    assert "host_d9_draw(&d);" in output
    assert "pl.rs[27], pl.rs[19], pl.rs[20]" in output
    UPDATE.patch_update_texture(kit)
    PROBE.patch_brightness_probe(kit)
    assert path.read_text() == output

def test_probe_fails_closed_before_mutation_on_source_drift(tmp_path):
    kit = fixture(tmp_path)
    UPDATE.patch_update_texture(kit)
    path = kit / PROBE.TARGET
    corrupted = path.read_text().replace(PROBE.DRAW_OLD, "invalid gpu draw")
    path.write_text(corrupted)
    with pytest.raises(RuntimeError, match="GPU draw instrumentation"):
        PROBE.patch_brightness_probe(kit)
    assert path.read_text() == corrupted

def test_probe_is_diagnostics_only(tmp_path):
    kit = fixture(tmp_path)
    UPDATE.patch_update_texture(kit)
    PROBE.patch_brightness_probe(kit)
    result = (kit / PROBE.TARGET).read_text()
    assert "REFLEX_BRIGHTNESS_PROBE" in result
    assert "LOGW(\"[reflex-brightness] texture" in result
    assert "LOGW(\"[reflex-brightness] draw" in result
    assert "host_d9_draw(&d);" in result
    assert "memcpy(b->blob.data(), a->blob.data(), a->blob.size());" in result
