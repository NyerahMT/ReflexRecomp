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


def test_offscreen_readback_is_bounded_and_never_replaces_guest_output():
    # The probe adds real, bounded GPU observations at selected original draws.
    code = PROBE.DRAW_NEW
    assert code.count("host_d9_draw(&d);") == 1
    assert "reflex-offscreen-rgb-alpha-probe-v1" in code
    assert "tracing ? com_get(pl.color_target[0]) : nullptr" in code
    assert "off_flag[1] == '\\0'" in code
    assert "off_rt->kind == K_D3D9SURFACE" in code
    assert "owner->kind == K_D3D9TEXTURE" in code
    assert "mirror_slot(off_rt, &slot)" in code
    assert "surface_ref(off_rt)" in code
    assert "od == 65536u" in code
    assert "uint64_t(off_rt->width) * off_rt->height <= 2048u * 2048u" in code
    assert 'snap("before");' in code
    assert 'snap("after");' in code
    assert code.index('snap("before");') < code.index("host_d9_draw(&d);")
    assert code.index('snap("after");') > code.index("host_d9_draw(&d);")
    assert "host_d9_texture_read(" in code
    assert "host_d9_texture_upload(" not in code
    assert "host_d9_clear(" not in code
    assert "REFLEX_BRIGHTNESS_PROBE" in code


def test_first_real_shader_sampler_alpha_is_read_only_and_format_checked():
    # Draw #8 generates the first visible original UI fragments. To distinguish
    # alpha in its sampled texture from alpha computed by the pixel shader,
    # inspect the bound GPU texture without overriding either one.
    code = PROBE.DRAW_NEW
    assert code.count("host_d9_draw(&d);") == 1
    assert code.count("reflex-source-alpha-probe-v1") == 1
    assert code.count("[reflex-source-alpha] bound") == 1
    assert code.count("[reflex-source-alpha] pixels") == 1
    assert "sampler0 = checkpoint ? com_get(pl.sampler_tex[0]) : nullptr" in code
    assert "sampler0->kind == K_D3D9TEXTURE" in code
    assert "sampler0->rmask == 21u || sampler0->rmask == 22u" in code
    assert "uint64_t(sampler0->width) * sampler0->height <= 2048u * 2048u" in code
    assert "host_d9_texture_read(" in code
    assert "sampler0->id, 0u, 0u, src_rgba.data(), src_pitch" in code
    assert "rgb_peak" in code and "alpha_peak" in code
    for bucket in ("a0", "a1_15", "a16_254", "a255"):
        assert bucket in code
    assert code.index("const bool checkpoint") < code.index("const bool sampleable")
    assert code.index("const bool sampleable") < code.index("if (sampleable)")
    assert code.index("if (sampleable)") < code.index("host_d9_draw(&d);")
    assert "host_d9_texture_upload(" not in code
    assert "host_d9_clear(" not in code
    assert "pl.rs[27] =" not in code


def test_original_pixel_shader_alpha_writes_traced_without_replacement():
    code = PROBE.DRAW_NEW
    assert code.count("reflex-shader-output-alpha-trace-v1") == 1
    assert code.count("[reflex-shader-alpha] original") == 1
    assert "if (checkpoint)" in code
    assert "for (const d9sh::Inst &in : ps.code)" in code
    assert "in.dst.type != d9sh::R_COLOROUT || in.dst.index != 0u" in code
    assert "in.dst.mask & 8u" in code
    assert "color0_alpha_writes" in code and "color0_rgb_writes" in code
    assert "last_alpha_mask" in code and "last_alpha_op" in code
    assert "d9sh::OP_TEXLDL" in code
    assert "d9sh::OP_CMP" in code
    assert "static_cast<unsigned long long>(d.ps_key)" in code
    assert code.count("host_d9_draw(&d);") == 1
    assert code.index("[reflex-shader-alpha] original") < code.index("host_d9_draw(&d);")
    assert "pl.ps =" not in code
    assert "pl.rs[27] =" not in code
    assert "host_d9_clear(" not in code
