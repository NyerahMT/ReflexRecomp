"""Regression: Direct3D9 alpha-only sampler must preserve white RGB + source A."""
from pathlib import Path
import importlib.util
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vulkan_a8", ROOT / "tools" / "patch_reflex_vulkan_a8.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def test_vulkan_alpha_only_swizzle_fails_closed_and_is_idempotent(tmp_path):
    kit = tmp_path / "kit"
    file = kit / patch.TARGET
    file.parent.mkdir(parents=True)
    # Include two non-A8 view definitions: only the documented alpha-only
    # sampled view may be touched.
    snippet = (
        "static View raw_view(bool alpha_only) {\n"
        "    View vci;\n" + patch.BEFORE +
        "    return vci;\n}\n"
        "static View ordinary_rgba() {\n"
        "    View vci;\n"
        "    vci.components = {VK_COMPONENT_SWIZZLE_IDENTITY};\n"
        "    return vci;\n}\n"
    )
    file.write_text(snippet)
    patch.patch_vulkan_a8(kit)
    result = file.read_text()
    assert result.count(patch.MARKER) == 1
    assert result.count(patch.AFTER) == 1
    assert result.count("VK_COMPONENT_SWIZZLE_ONE") == 3
    assert "VK_COMPONENT_SWIZZLE_R};" in result
    assert "ordinary_rgba()" in result
    assert "VK_COMPONENT_SWIZZLE_IDENTITY" in result
    assert patch.BEFORE not in result
    patch.patch_vulkan_a8(kit)
    assert file.read_text() == result

    # If the kit was changed upstream, do not patch a guessed layout.
    changed = snippet.replace("VK_COMPONENT_SWIZZLE_R};",
                              "VK_COMPONENT_SWIZZLE_A};", 1)
    file.write_text(changed)
    with pytest.raises(RuntimeError, match="Pinned Vulkan A8 sample"):
        patch.patch_vulkan_a8(kit)
    assert file.read_text() == changed


def test_actual_pinned_backend_a8_swizzle_and_cpu_agree(tmp_path):
    vulkan = ROOT / "kit" / patch.TARGET
    cpu = ROOT / "kit" / "dx" / "d3d9_raster.cpp"
    if not vulkan.is_file() or not cpu.is_file():
        pytest.skip("Pinned recomp-kit checkout only available during CI")
    text = cpu.read_text()
    assert "case 28: // A8" in text
    assert "o[0] = o[1] = o[2] = 255;" in text
    kit = tmp_path / "kit"
    dest = kit / patch.TARGET
    dest.parent.mkdir(parents=True)
    shutil.copyfile(vulkan, dest)
    patch.patch_vulkan_a8(kit)
    assert patch.MARKER in dest.read_text()
    assert "VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ZERO" not in dest.read_text()
