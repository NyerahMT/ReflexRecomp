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

    // CVTPS2PD XMM0,XMM0: convert both low floats, replacing all lanes.
    for (int i=0; i<4; ++i) setlane(c, 0, i, i == 0 ? 1.5f : -2.25f);
    code(0x11100, {0x0f,0x5a,0xc0});
    reflex_packed_sse(&c, 0x11100);
    double d0 = 0, d1 = 0;
    memcpy(&d0, &c.xmm[0][0], 8);
    memcpy(&d1, &c.xmm[0][2], 8);
    assert(d0 == 1.5 && d1 == -2.25);

    // CVTPD2PS XMM0,XMM0: mandatory 66 prefix and high 64 bits cleared.
    code(0x11110, {0x66,0x0f,0x5a,0xc0});
    reflex_packed_sse(&c, 0x11110);
    assert(lane(c, 0, 0) == 1.5f);
    assert(lane(c, 0, 1) == -2.25f);
    assert(c.xmm[0][2] == 0 && c.xmm[0][3] == 0);

    // CVTPS2PD XMM2, m64: read two floats and not an unnecessary 16 bytes.
    const float cv_input[] = {0.25f, -16.0f};
    memcpy(g_mem + 0x17030, cv_input, sizeof cv_input);
    code(0x11120, {0x0f,0x5a,0x15,0x30,0x70,0x01,0x00});
    reflex_packed_sse(&c, 0x11120);
    memcpy(&d0, &c.xmm[2][0], 8);
    memcpy(&d1, &c.xmm[2][2], 8);
    assert(d0 == 0.25 && d1 == -16.0);

    // Packed comparison masks: NEQ is true for unequal or unordered NaNs.
    setlane(c, 1, 0, 1.f); setlane(c, 1, 1, 2.f);
    setlane(c, 1, 2, 3.f); setlane(c, 1, 3, 4.f);
    setlane(c, 2, 0, 1.f); setlane(c, 2, 1, 3.f);
    setlane(c, 2, 2, std::nanf("")); setlane(c, 2, 3, 2.f);
    code(0x11130, {0x0f,0xc2,0xca,0x04}); // CMPNEQPS xmm1,xmm2
    reflex_packed_sse(&c, 0x11130);
    assert(c.xmm[1][0] == 0 && c.xmm[1][1] == UINT32_MAX);
    assert(c.xmm[1][2] == UINT32_MAX && c.xmm[1][3] == UINT32_MAX);

    // Scalar CMPNLESS and CMPNLESD preserve their upper lanes.
    setlane(c, 1, 0, 4.f); setlane(c, 2, 0, 3.f);
    c.xmm[1][1] = 0x11223344u;
    c.xmm[1][2] = 0x55667788u;
    c.xmm[1][3] = 0x99aabbccu;
    code(0x11140, {0xf3,0x0f,0xc2,0xca,0x06});
    reflex_packed_sse(&c, 0x11140);
    assert(c.xmm[1][0] == UINT32_MAX &&
           c.xmm[1][1] == 0x11223344u &&
           c.xmm[1][2] == 0x55667788u &&
           c.xmm[1][3] == 0x99aabbccu);
    double large = 20.0, small = 5.0;
    memcpy(&c.xmm[1][0], &large, 8);
    memcpy(&c.xmm[2][0], &small, 8);
    code(0x11150, {0xf2,0x0f,0xc2,0xca,0x06});
    reflex_packed_sse(&c, 0x11150);
    assert(c.xmm[1][0] == UINT32_MAX && c.xmm[1][1] == UINT32_MAX &&
           c.xmm[1][2] == 0x55667788u && c.xmm[1][3] == 0x99aabbccu);

    // DIVPS and SQRTPS lanes, plus exact source-bit choice for MINPS/MAXPS.
    for (int i=0; i<4; ++i) {
        setlane(c, 3, i, 16.0f * (i + 1));
        setlane(c, 2, i, 2.0f);
    }
    code(0x11160, {0x0f,0x5e,0xda}); // DIVPS xmm3,xmm2
    reflex_packed_sse(&c, 0x11160);
    const float quotients[] = {8,16,24,32};
    verify(c, 3, quotients);
    code(0x11170, {0x0f,0x51,0xd3}); // SQRTPS xmm2,xmm3
    reflex_packed_sse(&c, 0x11170);
    const float roots[] = {std::sqrt(8.f),4.f,std::sqrt(24.f),std::sqrt(32.f)};
    verify(c, 2, roots);

    c.xmm[1][0] = 0x00000000u; // +0
    c.xmm[2][0] = 0x80000000u; // -0
    c.xmm[1][1] = 0x7fc00001u; // NaN payload
    c.xmm[2][1] = 0x3f800000u; // 1
    code(0x11180, {0x0f,0x5d,0xca}); // MINPS xmm1,xmm2
    reflex_packed_sse(&c, 0x11180);
    assert(c.xmm[1][0] == 0x80000000u && c.xmm[1][1] == 0x3f800000u);
    c.xmm[1][0] = 0x00000000u;
    c.xmm[2][0] = 0x80000000u;
    code(0x11190, {0x0f,0x5f,0xca}); // MAXPS xmm1,xmm2
    reflex_packed_sse(&c, 0x11190);
    assert(c.xmm[1][0] == 0x80000000u);

    // Deliberately unsupported approximate reciprocal family fails explicitly.
    code(0x111a0, {0x0f,0x53,0xca}); // RCPPS
    reflex_packed_sse(&c, 0x111a0);
    assert(traps == 3);
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
