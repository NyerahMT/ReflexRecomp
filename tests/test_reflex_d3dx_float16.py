"""Exercise portable D3DXFLOAT16 conversion independently of game binaries."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = r"""
#include "reflex_d3dx_float16.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <limits>

static uint16_t convert(float x) {
    uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(x));
    std::memcpy(&bits, &x, sizeof(bits));
    return reflex_d3dx::f32_to_f16_bits(bits);
}
int main() {
    assert(convert(0.0f) == 0x0000u);
    assert(convert(-0.0f) == 0x8000u);
    assert(convert(1.0f) == 0x3c00u);
    assert(convert(-2.0f) == 0xc000u);
    assert(convert(65504.0f) == 0x7bffu);
    assert(convert(65536.0f) == 0x7c00u);
    assert(convert(std::numeric_limits<float>::infinity()) == 0x7c00u);
    assert(convert(-std::numeric_limits<float>::infinity()) == 0xfc00u);
    assert(convert(0.00006103515625f) == 0x0400u); // smallest normal
    assert(convert(0.000000059604644775390625f) == 0x0001u); // smallest subnormal
    assert(convert(0.0000000298023223876953125f) == 0x0000u); // ties-to-even zero
    assert(convert(0.0000000894069671630859375f) == 0x0002u); // ties-to-even two
    assert(convert(1.00048828125f) == 0x3c00u); // halfway to next half
    assert(convert(1.00146484375f) == 0x3c02u); // halfway between 1 and 2 ulps
    assert((convert(std::numeric_limits<float>::quiet_NaN()) & 0x7e00u) == 0x7e00u);
}
"""


def test_d3dx_float32_to_16_native(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("Native C++ compiler not installed")
    source = tmp_path / "float16.cpp"
    executable = tmp_path / "float16"
    source.write_text(SRC)
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "runtime"), str(source), "-o", str(executable)],
                   capture_output=True, text=True, check=True)
    subprocess.run([str(executable)], capture_output=True, text=True, check=True)


def test_import_registered_with_correct_stdcall_arity():
    compat = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    patch = (ROOT / "tools" / "patch_reflex_runtime.py").read_text()
    assert '{"d3dx9_43.dll", "D3DXFloat32To16Array", 3, d3dx_float32_to16_array}' in compat
    assert "gm_valid(in, count * 4u)" in compat
    assert "gm_valid(out, count * 2u)" in compat
    assert "std::vector<uint32_t> source(count)" in compat
    assert 'D3DX_HALF_HEADER = ROOT / "runtime" / "reflex_d3dx_float16.h"' in patch
    assert "headers = (numeric, wide_format, fast_strings, d3dx_half)" in patch
