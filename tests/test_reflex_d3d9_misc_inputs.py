"""SM3 pixel position and face native shader translation regression."""
from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reflex_d3d9_misc_inputs", ROOT / "tools" / "patch_reflex_d3d9_misc_inputs.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

CPP = r"""
#include "d3d9_glsl.h"
#include "d3d9_msl.h"
#include "d3d9_wgsl.h"
#include <cassert>
#include <fstream>
#include <string>
#include <iostream>
using namespace d9sh;

Program misc(uint32_t index) {
    Program p;
    p.ok = true;
    p.pixel = true;
    p.major = 3;
    p.minor = 0;
    Inst mov{};
    mov.op = OP_MOV;
    mov.has_dst = true;
    mov.dst.type = R_COLOROUT;
    mov.dst.index = 0;
    mov.dst.mask = 15;
    mov.nsrc = 1;
    mov.src[0].type = R_MISC;
    mov.src[0].index = index;
    p.code.push_back(mov);
    return p;
}
int main(int argc, char **argv) {
    assert(argc == 3);
    d9msl::PixelVariant variant{};
    for (uint32_t i = 0; i < 2; ++i) {
        Program p = misc(i);
        std::string glsl, msl, wgsl, why;
        assert(d9glsl::pixel_source(p, variant, &glsl, &why));
        assert(d9msl::pixel_source(p, variant, &msl, &why));
        assert(d9wgsl::pixel_source(p, variant, &wgsl, &why));
        if (i == 0) {
            assert(glsl.find("gl_FragCoord.xy, 0.0, 0.0") != std::string::npos);
            assert(msl.find("vin.pos.xy, 0.0, 0.0") != std::string::npos);
            assert(wgsl.find("vin.pos.xy, 0.0, 0.0") != std::string::npos);
        } else {
            assert(glsl.find("gl_FrontFacing ? 1.0 : -1.0") != std::string::npos);
            assert(msl.find("face ? 1.0 : -1.0") != std::string::npos);
            assert(wgsl.find("select(-1.0, 1.0, face)") != std::string::npos);
        }
        assert(msl.find("bool face [[front_facing]]") != std::string::npos);
        assert(wgsl.find("@builtin(front_facing) face: bool") != std::string::npos);
        std::ofstream(i ? argv[2] : argv[1]) << glsl;
    }
    {
        Program bad = misc(2);
        std::string source, why;
        assert(!d9glsl::pixel_source(bad, variant, &source, &why));
        assert(why.find("unsupported misc register 2") != std::string::npos);
        bad = misc(0);
        bad.major = 2;
        why.clear();
        assert(!d9msl::pixel_source(bad, variant, &source, &why));
        assert(why.find("unsupported misc register 0") != std::string::npos);
        bad = misc(1);
        bad.pixel = false;
        why.clear();
        assert(!d9glsl::vertex_source(bad, &source, &why));
        assert(why.find("unsupported misc register 1") != std::string::npos);
    }
    return 0;
}
"""

def fixture(tmp_path):
    kit = ROOT / "kit"
    target = kit / PATCH.TARGET
    if not target.is_file():
        pytest.skip("Pinned kit only accessible in CI checkout")
    dest = tmp_path / "kit" / PATCH.TARGET
    dest.parent.mkdir(parents=True)
    shutil.copyfile(target, dest)
    return dest.parent.parent

def test_misc_patch_idempotence_and_fails_closed(tmp_path):
    kit = fixture(tmp_path)
    target = kit / PATCH.TARGET
    PATCH.patch_misc_inputs(kit)
    patched = target.read_text()
    assert patched.count(PATCH.MARKER) == 1
    assert patched.count(PATCH.SOURCE_NEW) == 1
    assert patched.count(PATCH.MSL_NEW) == 1
    assert patched.count(PATCH.WGSL_NEW) == 1
    PATCH.patch_misc_inputs(kit)
    assert target.read_text() == patched
    changed = patched.replace(PATCH.MARKER, "broken-marker", 1)
    target.write_text(changed)
    with pytest.raises(RuntimeError, match="pinned source register decoder"):
        PATCH.patch_misc_inputs(kit)
    assert target.read_text() == changed

def test_native_sm3_pixel_misc_register_sources(tmp_path):
    kit = fixture(tmp_path)
    PATCH.patch_misc_inputs(kit)
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    cpp = tmp_path / "misc.cpp"
    exe = tmp_path / "misc"
    frag_pos = tmp_path / "vpos.frag"
    frag_face = tmp_path / "vface.frag"
    cpp.write_text(CPP)
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "kit" / "dx"),
                    str(cpp), str(kit / PATCH.TARGET), "-o", str(exe)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(exe), str(frag_pos), str(frag_face)],
                   check=True, capture_output=True, text=True)
    validator = shutil.which("glslangValidator")
    if validator:
        for frag in (frag_pos, frag_face):
            subprocess.run([validator, "-V", "-S", "frag", str(frag),
                            "-o", str(frag.with_suffix(".spv"))],
                           check=True, capture_output=True, text=True)
