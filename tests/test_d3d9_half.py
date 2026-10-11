"""Native IEEE-754 half-float and pinned D3D9 patch regression coverage."""
from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "runtime" / "reflex_d3d9_half.h"
PINNED_KIT = ROOT / "kit"
spec = importlib.util.spec_from_file_location(
    "reflex_half_patch", ROOT / "tools" / "patch_reflex_d3d9_half.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

HARNESS = r"""
#include "reflex_d3d9_half.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

static uint32_t bits(float value) {
    uint32_t out;
    std::memcpy(&out, &value, 4);
    return out;
}
int main() {
    using reflex_d3d9::float16_to_float32;
    assert(bits(float16_to_float32(0x0000u)) == 0x00000000u);
    assert(bits(float16_to_float32(0x8000u)) == 0x80000000u);
    assert(bits(float16_to_float32(0x3c00u)) == 0x3f800000u);
    assert(bits(float16_to_float32(0xbc00u)) == 0xbf800000u);
    assert(bits(float16_to_float32(0x4000u)) == 0x40000000u);
    assert(bits(float16_to_float32(0x0001u)) == 0x33800000u);
    assert(bits(float16_to_float32(0x03ffu)) == 0x387fc000u);
    assert(bits(float16_to_float32(0x0400u)) == 0x38800000u);
    assert(bits(float16_to_float32(0x7bffu)) == 0x477fe000u);
    assert(std::isinf(float16_to_float32(0x7c00u)));
    assert(std::isinf(float16_to_float32(0xfc00u)));
    assert(std::isnan(float16_to_float32(0x7e00u)));
    assert(std::isnan(float16_to_float32(0xfe01u)));
    const uint8_t vertex[8] = {0x00, 0x3c, 0x00, 0xc0, 0x00, 0x38, 0x00, 0x34};
    assert(reflex_d3d9::float16_component(vertex, 0) == 1.0f);
    assert(reflex_d3d9::float16_component(vertex, 1) == -2.0f);
    assert(reflex_d3d9::float16_component(vertex, 2) == 0.5f);
    assert(reflex_d3d9::float16_component(vertex, 3) == 0.25f);
    assert(reflex_d3d9::vertex_element_bytes(15) == 4);
    assert(reflex_d3d9::vertex_element_bytes(16) == 8);
    assert(reflex_d3d9::vertex_element_bytes(4) == 4);
    assert(reflex_d3d9::vertex_element_bytes(3) == 16);
    assert(reflex_d3d9::vertex_element_bytes(17) == 0);
    return 0;
}
"""


def test_ieee754_binary16_to_binary32(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no native compiler")
    assert HEADER.exists()
    source, binary = tmp_path / "half.cpp", tmp_path / "half"
    source.write_text(HARNESS)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def _copy_kit(tmp_path):
    pinned = PINNED_KIT / "dx"
    if not (pinned / "d3d9.cpp").exists() or not (pinned / "d3d9_raster.cpp").exists():
        pytest.skip("pinned recomp-kit absent (available in GitHub CI)")
    dest = tmp_path / "kit" / "dx"
    dest.mkdir(parents=True)
    for name in ("d3d9.cpp", "d3d9_raster.cpp"):
        shutil.copyfile(pinned / name, dest / name)
    return dest.parent


def test_pinned_d3d9_half_patcher_atomic_idempotent(tmp_path):
    kit = _copy_kit(tmp_path)
    patcher.patch_float16(kit, ROOT / "runtime")
    raster = (kit / "dx" / "d3d9_raster.cpp").read_text()
    d3d = (kit / "dx" / "d3d9.cpp").read_text()
    assert raster.count("case 15: // FLOAT16_2") == 1
    assert raster.count("case 16: // FLOAT16_4") == 1
    assert "call.stride - e.offset" in raster
    assert d3d.count(patcher.MARKER) == 1
    assert "float16_component(data, 0)" in d3d
    assert (kit / "dx" / "reflex_d3d9_half.h").exists()
    patcher.patch_float16(kit, ROOT / "runtime")
    assert (kit / "dx" / "d3d9_raster.cpp").read_text() == raster
    assert (kit / "dx" / "d3d9.cpp").read_text() == d3d


def test_half_patcher_fails_without_mutating_sources(tmp_path):
    kit = _copy_kit(tmp_path)
    raster_file = kit / "dx" / "d3d9_raster.cpp"
    d3d_file = kit / "dx" / "d3d9.cpp"
    # Mutate the exact CPU vertex fetch anchor, not another unrelated case 7.
    needle = "            v[k] = (int16_t)(c[2 * k] | c[2 * k + 1] << 8);"
    assert raster_file.read_text().count(needle) == 1
    broken = raster_file.read_text().replace(needle, "            v[k] = 0;")
    raster_file.write_text(broken)
    original_d3d = d3d_file.read_text()
    with pytest.raises(RuntimeError, match="CPU vertex type switch"):
        patcher.patch_float16(kit, ROOT / "runtime")
    assert d3d_file.read_text() == original_d3d
    assert raster_file.read_text() == broken


def test_fvf_and_float16_patch_order_in_both_workflows():
    # The FVF helper needs the existing swap-chain COM additions; FLOAT16
    # operates on the shader/vertex declarations after the other patches.
    for workflow in ("fast-iterate.yml", "ios-native.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text()
        names = ("patch_reflex_d3d9_shaders.py",
                 "patch_reflex_d3d9_swapchain.py",
                 "patch_reflex_d3d9_fvf.py",
                 "patch_reflex_d3d9_half.py")
        positions = [text.index("python3 tools/" + name) for name in names]
        assert positions == sorted(positions)
