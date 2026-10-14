"""Synthetic D3D9 fixed-function shader correctness and fail-closed patches."""
from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "runtime" / "reflex_d3d9_ffp_quad.h"

spec = importlib.util.spec_from_file_location(
    "reflex_quad_patch", ROOT / "tools" / "patch_reflex_d3d9_ffp_quad.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


CPP = r"""
#include "reflex_d3d9_ffp_quad.h"
#include <cassert>
#include <cmath>
#include <cstdint>
int main() {
    const auto &vs = reflex_ffp::quad_vs();
    const auto &ps = reflex_ffp::quad_ps();
    assert(vs.size() == 25u * 4u); // version, dcls, three ops, END
    assert(ps.size() == 15u * 4u);
    assert(vs[0] == 0 && vs[1] == 3 && vs[2] == 0xfe && vs[3] == 0xff);
    assert(ps[0] == 0 && ps[1] == 3 && ps[2] == 0xff && ps[3] == 0xff);
    assert(reflex_ffp::supported(0x104, 17, 4, 2, 1, 2, 2, 1));
    assert(!reflex_ffp::supported(0x104, 0, 4, 2, 1, 2, 2, 1));
    assert(!reflex_ffp::supported(0x144, 17, 4, 2, 1, 2, 2, 1));
    assert(!reflex_ffp::supported(0x104, 17, 2, 2, 1, 2, 2, 1));
    assert(!reflex_ffp::supported(0x104, 17, 4, 2, 1, 2, 2, 4));
    // From original-game run 171: 24-byte D3DVERTEXELEMENT9 record.
    uint8_t decl[24] = {
        0, 0, 0, 0, 3, 0, 9, 0,       // stream0 positionT float4 @0
        0, 0, 16, 0, 1, 0, 5, 0,      // stream0 texcoord0 float2 @16
        255, 0, 0, 0, 17, 0, 0, 0,    // D3DDECL_END
    };
    assert(reflex_ffp::supported_decl(decl, sizeof(decl), 24));
    assert(!reflex_ffp::supported_decl(nullptr, sizeof(decl), 24));
    assert(!reflex_ffp::supported_decl(decl, sizeof(decl) - 8, 24));
    assert(!reflex_ffp::supported_decl(decl, sizeof(decl), 0));
    assert(!reflex_ffp::supported_decl(decl, sizeof(decl), 20));
    assert(!reflex_ffp::supported_decl(decl, sizeof(decl), 28));
    // Refuse superficially similar but semantically different vertex formats.
    for (unsigned index : {0u, 2u, 4u, 5u, 6u, 7u, 10u, 12u, 14u, 20u, 23u}) {
        decl[index] ^= 1u;
        assert(!reflex_ffp::supported_decl(decl, sizeof(decl), 24));
        decl[index] ^= 1u;
        assert(reflex_ffp::supported_decl(decl, sizeof(decl), 24));
    }
    float m[2][4] = {};
    assert(reflex_ffp::clip_constants(0, 0, 1280, 720, m));
    assert(std::fabs(m[0][0] - 2.f / 1280.f) < 0.00001f);
    assert(std::fabs(m[0][1] + 2.f / 720.f) < 0.00001f);
    assert(m[0][2] == 1.f && m[0][3] == 0.f);
    assert(m[1][0] == -1.f && m[1][1] == 1.f);
    assert(m[1][2] == 0.f && m[1][3] == 1.f);
    assert(!reflex_ffp::clip_constants(0, 0, 0, 720, m));
    assert(!reflex_ffp::clip_constants(0, 0, 1280, 0, m));
    return 0;
}
"""

PINNED = r"""
#include "reflex_d3d9_ffp_quad.h"
#include "d3d9_shader.h"
#include "d3d9_glsl.h"
#include "d3d9_msl.h"
#include <cassert>
#include <string>
int main() {
    const d9sh::Program &vs = d9sh::program_for(reflex_ffp::quad_vs());
    const d9sh::Program &ps = d9sh::program_for(reflex_ffp::quad_ps());
    assert(vs.ok && !vs.pixel && vs.major == 3);
    assert(ps.ok && ps.pixel && ps.major == 3);
    assert(vs.inputs.size() == 2 && vs.outputs.size() == 2);
    assert(vs.inputs[0].usage == 9 && vs.inputs[1].usage == 5);
    assert(vs.outputs[0].usage == 0 && vs.outputs[1].usage == 5);
    assert(vs.max_const == 2);
    assert(ps.inputs.size() == 1 && ps.inputs[0].usage == 5);
    assert(ps.samplers.at(0) == d9sh::S_2D);
    assert(d9msl::pixel_sampler_mask(ps) == 1);
    std::string shader, why;
    assert(d9glsl::vertex_source(vs, &shader, &why));
    assert(shader.find("gl_Position") != std::string::npos);
    assert(shader.find("c[1]") != std::string::npos);
    assert(d9glsl::pixel_source(ps, d9msl::PixelVariant{}, &shader, &why));
    assert(shader.find("sampler2D") != std::string::npos);
    assert(d9msl::vertex_source(vs, &shader, &why));
    assert(shader.find("vs_main") != std::string::npos);
    assert(d9msl::pixel_source(ps, d9msl::PixelVariant{}, &shader, &why));
    assert(shader.find("ps_main") != std::string::npos);
    return 0;
}
"""


def compiler():
    return shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")


def test_quad_shader_tokens_and_clip_transform(tmp_path):
    cxx = compiler()
    if not cxx:
        pytest.skip("no native C++ compiler")
    code, binary = tmp_path / "quad.cpp", tmp_path / "quad"
    code.write_text(CPP)
    subprocess.run(
        [cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(code), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_generated_shaders_decode_and_compile_to_glsl_msl(tmp_path):
    kit = ROOT / "kit" / "dx"
    if not (kit / "d3d9_shader.cpp").exists():
        pytest.skip("Pinned recomp-kit checked out during GitHub CI")
    cxx = compiler()
    if not cxx:
        pytest.skip("no native C++ compiler")
    code, binary = tmp_path / "translate.cpp", tmp_path / "translate"
    code.write_text(PINNED)
    subprocess.run(
        [cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), "-I", str(kit), str(code),
         str(kit / "d3d9_shader.cpp"), str(kit / "d3d9_shadergen.cpp"),
         "-o", str(binary)], check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_ffp_patcher_fails_closed_and_does_not_duplicate(tmp_path):
    kit = tmp_path / "kit"
    (kit / "dx").mkdir(parents=True)
    target = kit / "dx" / "d3d9.cpp"
    source = '''#include "com.h"
static void gpu_draw(ComObj *dev, HostD9Draw &d) {
    D9Pipeline &pl = d9_pipeline(dev->id);
    if (pl.vs.empty() || pl.ps.empty()) {
        static std::atomic<unsigned long long> skips{0};
        log_once("d3d9.gpu.ffp", "skipped");
        return;
    }
    d.target = gpu_target(dev);
    target_viewport(dev, d.target, d.viewport);
    if (!pl.vs_key)
        pl.vs_key = d9sh::code_key(pl.vs.data(), pl.vs.size());
    if (!pl.ps_key)
        pl.ps_key = d9sh::code_key(pl.ps.data(), pl.ps.size());
    const d9sh::Program &vs = d9sh::program_for_key(pl.vs_key, pl.vs.data(), pl.vs.size());
    const d9sh::Program &ps = d9sh::program_for_key(pl.ps_key, pl.ps.data(), pl.ps.size());
    d.vs_key = pl.vs_key;
    d.ps_key = pl.ps_key;
    d.vs = pl.vs.data();
    d.vs_size = (uint32_t)pl.vs.size();
    d.ps = pl.ps.data();
    d.ps_size = (uint32_t)pl.ps.size();
    d.vconst = &pl.vconst[0][0];
    d.vconst_count = std::min<uint32_t>(vs.max_const, 256);
    d.pconst = &pl.pconst[0][0];
    d.pconst_count = std::min<uint32_t>(ps.max_const, 32);
}
'''
    target.write_text(source)
    patch.patch_ffp_quad(kit, ROOT / "runtime")
    changed = target.read_text()
    assert changed.count(patch.MARKER) == 1
    assert changed.count("[reflex-ffp] textured-fvf") == 1
    assert changed.count("reflex-ffp-declaration-quad-v1") == 1
    assert changed.count("[reflex-ffp] textured-decl") == 1
    assert "reflex_ffp::supported_decl(ffp_decl->blob.data()" in changed
    assert "d.inline_vertices ?" in changed
    assert "ffp_flag[1]" in changed
    assert "pl.vs.empty() && pl.ps.empty()" in changed
    assert changed.count("[reflex-ffp] declined-decl") == 1
    assert changed.count("[reflex-ffp] decl-element") == 1
    assert "if (!fallback) {" in changed
    assert "m <= 2 || m == 32" in changed
    assert "std::min<size_t>(bytes, 128u)" in changed
    assert "if (stream == 0xffu) break;" in changed
    assert "d.vs = vs_bytes.data();" in changed
    assert "std::getenv" in changed
    assert patch.patch_ffp_quad(kit, ROOT / "runtime") is None
    assert target.read_text() == changed

    target.write_text(source.replace("    if (!pl.vs_key)", "    if (pl.vs_key)"))
    with pytest.raises(RuntimeError, match="native GPU shader selection"):
        patch.patch_ffp_quad(kit, ROOT / "runtime")
    assert (kit / "dx" / "d3d9.cpp").read_text().startswith('#include "com.h"\n')
