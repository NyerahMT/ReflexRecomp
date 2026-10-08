"""Native decoder tests against the actual pinned recomp-kit X86 ABI."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
#include "reflex_packed_sse.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

extern "C" {
uint8_t *g_mem = nullptr;
static unsigned traps = 0;
void recomp_unmodelled(X86 *, uint32_t) { ++traps; }
}

void setlane(X86 &c, unsigned reg, unsigned lane, float value) {
    memcpy(&c.xmm[reg][lane], &value, 4);
}
float lane(const X86 &c, unsigned reg, unsigned lane) {
    float value;
    memcpy(&value, &c.xmm[reg][lane], 4);
    return value;
}
void source(uint32_t ptr, const float vals[4]) {
    memcpy(g_mem + ptr, vals, 4 * sizeof(float));
}
void code(uint32_t addr, const std::vector<uint8_t> &bytes) {
    memcpy(g_mem + addr, bytes.data(), bytes.size());
}
void verify(const X86 &c, unsigned reg, const float vals[4]) {
    for (unsigned i = 0; i < 4; ++i)
        assert(std::fabs(lane(c, reg, i) - vals[i]) < 0.00001f);
}

int main() {
    std::vector<uint8_t> mem(0x30000u);
    g_mem = mem.data();
    X86 c{};
    c.r[R_EAX] = 0x15000;
    c.r[R_ECX] = 2;
    c.r[R_EBP] = 0x16010;
    c.r[R_ESP] = 0x18000;

    const float x[] = {1,2,3,4};
    const float y[] = {5,6,7,8};
    for (int i=0;i<4;++i) {
        setlane(c, 1, i, x[i]);
        setlane(c, 2, i, y[i]);
    }
    code(0x11000, {0x0f,0x58,0xca}); // ADDPS XMM1,XMM2
    reflex_packed_sse(&c, 0x11000);
    const float summed[] = {6,8,10,12};
    verify(c, 1, summed);

    for (int i=0;i<4;++i) setlane(c, 0, i, x[i]);
    code(0x11010, {0x0f,0x59,0xc0}); // MULPS XMM0,XMM0
    reflex_packed_sse(&c, 0x11010);
    const float squares[] = {1,4,9,16};
    verify(c, 0, squares);

    source(0x15018, x);
    for (int i=0;i<4;++i) setlane(c, 3, i, 10.0f * (i+1));
    code(0x11020, {0x0f,0x5c,0x5c,0x88,0x10});
    // SUBPS XMM3,[EAX + ECX*4 + 0x10] (8-bit displacement + SIB)
    reflex_packed_sse(&c, 0x11020);
    const float subtracted[] = {9,18,27,36};
    verify(c, 3, subtracted);

    source(0x17000, y);
    for (int i=0;i<4;++i) setlane(c, 2, i, x[i]);
    code(0x11030, {0x0f,0x59,0x15,0x00,0x70,0x01,0x00});
    // MULPS XMM2, [absolute 0x00017000]
    reflex_packed_sse(&c, 0x11030);
    const float multiplied[] = {5,12,21,32};
    verify(c, 2, multiplied);

    source(0x18008, x);
    code(0x11040, {0x0f,0x58,0x44,0x24,0x08});
    // ADDPS XMM0, [ESP+8]
    reflex_packed_sse(&c, 0x11040);
    const float added_to_squares[] = {2,6,12,20};
    verify(c, 0, added_to_squares);

    source(0x16000, y);
    code(0x11050, {0x0f,0x5c,0x45,0xf0});
    // SUBPS XMM0, [EBP-16]
    reflex_packed_sse(&c, 0x11050);
    const float final_values[] = {-3,0,5,12};
    verify(c, 0, final_values);

    code(0x11060, {0x66,0x0f,0x58,0xca}); // ADDPD is not ADDPS
    reflex_packed_sse(&c, 0x11060);
    assert(traps == 1);
    c.r[R_EAX] = 0;
    code(0x11070, {0x0f,0x59,0x00}); // invalid null source
    reflex_packed_sse(&c, 0x11070);
    assert(traps == 2);
    return 0;
}
"""


def test_native_packed_single_x86_decode(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    pinned = ROOT / "kit" / "runtime" / "x86.h"
    if not compiler or not pinned.exists():
        pytest.skip("pinned recomp-kit checkout or C++ compiler unavailable")
    source = tmp_path / "simd_fixture.cpp"
    binary = tmp_path / "simd_fixture"
    source.write_text(HARNESS)
    subprocess.run(
        [compiler, "-std=c++17", "-O1", "-Wall", "-Wextra",
         "-I", str(ROOT / "runtime"),
         "-I", str(ROOT / "kit" / "runtime"),
         str(source), str(ROOT / "runtime" / "reflex_packed_sse.cpp"),
         "-o", str(binary)], check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
