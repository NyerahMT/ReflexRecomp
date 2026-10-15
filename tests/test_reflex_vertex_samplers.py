"""Native shader-generation tests for original Reflex vertex texture fetches."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vertex_sampler_patch", ROOT / "tools/patch_reflex_vertex_samplers.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

CPP = r"""
#include "d3d9_glsl.h"
#include "d3d9_msl.h"
#include <cassert>
#include <string>
#include <fstream>
int main(int argc, char **argv) {
    assert(argc == 2);
    d9sh::Program v;
    v.ok = true;
    v.pixel = false;
    v.major = 3;
    v.minor = 0;
    v.samplers[0] = d9sh::S_2D;
    v.inputs.push_back({0, 0, d9sh::R_INPUT, 0});
    d9sh::Inst tex{};
    tex.op = d9sh::OP_TEX;
    tex.has_dst = true;
    tex.dst = {d9sh::R_TEMP, 0, 15, false, 0};
    tex.nsrc = 2;
    tex.src[0].type = d9sh::R_INPUT;
    tex.src[0].index = 0;
    tex.src[1].type = d9sh::R_SAMPLER;
    tex.src[1].index = 0;
    v.code.push_back(tex);
    assert(d9msl::pixel_sampler_mask(v) == 1u);
    std::string glsl, msl, why;
    assert(d9glsl::vertex_source(v, &glsl, &why));
    assert(d9msl::vertex_source(v, &msl, &why));
    assert(glsl.find("binding = 4) uniform sampler2D tx0;") != std::string::npos);
    assert(glsl.find("texture(tx0,") != std::string::npos);
    assert(msl.find("texture2d<float> tx0 [[texture(0)]]") != std::string::npos);
    assert(msl.find("sampler sm0 [[sampler(0)]]") != std::string::npos);
    std::ofstream(argv[1]) << glsl;
    // No texture-fetched instruction: no extraneous vertex textures.
    v.code.clear();
    assert(d9glsl::vertex_source(v, &glsl, &why));
    assert(glsl.find("uniform sampler2D tx0;") == std::string::npos);
    assert(d9msl::vertex_source(v, &msl, &why));
    assert(msl.find("texture2d<float> tx0 [[texture(0)]]") == std::string::npos);
}
"""

def kit_fixture(tmp_path):
    real = ROOT / "kit"
    files = [patch.SHADERGEN, patch.VULKAN, patch.METAL]
    if not all((real / file).is_file() for file in files):
        pytest.skip("Pinned kit only available in CI checkout")
    kit = tmp_path / "kit"
    for f in files:
        t = kit / f
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real / f, t)
    return kit

def test_patch_idempotence_and_vertex_descriptors(tmp_path):
    kit = kit_fixture(tmp_path)
    patch.patch_vertex_samplers(kit)
    sg = (kit / patch.SHADERGEN).read_text()
    vk = (kit / patch.VULKAN).read_text()
    mt = (kit / patch.METAL).read_text()
    assert sg.count(patch.MARKER) == 1
    assert "for (uint32_t st : g.stages)" in sg
    assert "VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT" in vk
    assert "d9msl::pixel_sampler_mask(vp)" in vk
    assert "vertex_used = d9msl::pixel_sampler_mask(vp)" in mt
    assert "[enc_ setVertexTexture:use atIndex:s]" in mt
    assert "[enc_ setVertexSamplerState:smp atIndex:s]" in mt
    patch.patch_vertex_samplers(kit)
    assert sg == (kit / patch.SHADERGEN).read_text()
    assert vk == (kit / patch.VULKAN).read_text()
    assert mt == (kit / patch.METAL).read_text()

def test_patch_is_atomic_on_upstream_drift(tmp_path):
    kit = kit_fixture(tmp_path)
    vk = kit / patch.VULKAN
    vk.write_text(vk.read_text().replace(patch.VK_LAYOUT_OLD,
                                           "unsupported layout", 1))
    original = {p: (kit / p).read_text() for p in (patch.SHADERGEN,patch.VULKAN,patch.METAL)}
    with pytest.raises(RuntimeError, match="Vulkan sampler stage flags"):
        patch.patch_vertex_samplers(kit)
    assert original == {p: (kit / p).read_text()
                        for p in (patch.SHADERGEN,patch.VULKAN,patch.METAL)}

def test_generated_native_vulkan_and_metal_vertex_samples(tmp_path):
    kit = kit_fixture(tmp_path)
    patch.patch_vertex_samplers(kit)
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    src = tmp_path / "vertex.cpp"
    exe = tmp_path / "vertex"
    glsl = tmp_path / "vertex.vert"
    src.write_text(CPP)
    cmd = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
           "-I", str(ROOT / "kit" / "dx"), str(src),
           str(kit / patch.SHADERGEN), "-o", str(exe)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    subprocess.run([str(exe), str(glsl)], capture_output=True, text=True, check=True)
    validator = shutil.which("glslangValidator")
    if validator:
        subprocess.run([validator, "-V", "-S", "vert", str(glsl), "-o",
                        str(tmp_path / "vertex.spv")],
                       capture_output=True, text=True, check=True)
