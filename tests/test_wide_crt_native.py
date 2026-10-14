"""Native regression coverage for the reached MSVCR90 wide-string helpers."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"
BEGIN = "void crt_wcsncpy(X86 *c) {"
END = "void crt_rtc_initw(X86 *c) {"

HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>

constexpr uint32_t GUEST_SIZE = 16384u;
std::vector<uint8_t> guest(GUEST_SIZE);
uint8_t *g_mem = guest.data();

enum { R_EAX = 0, R_ESP = 4 };
struct X86 { uint32_t r[8] = {}; };

bool gm_valid(uint32_t p, uint32_t n) {
    return p < GUEST_SIZE && n <= GUEST_SIZE - p;
}
uint16_t rd16(uint32_t p) {
    assert(gm_valid(p, 2));
    uint16_t v = 0;
    memcpy(&v, g_mem + p, 2);
    return v;
}
void wr16(uint32_t p, uint16_t v) {
    assert(gm_valid(p, 2));
    memcpy(g_mem + p, &v, 2);
}
uint32_t rd32(uint32_t p) {
    assert(gm_valid(p, 4));
    uint32_t v = 0;
    memcpy(&v, g_mem + p, 4);
    return v;
}
void wr32(uint32_t p, uint32_t v) {
    assert(gm_valid(p, 4));
    memcpy(g_mem + p, &v, 4);
}
uint32_t arg(X86 *c, uint32_t n) {
    return rd32(c->r[R_ESP] + 4u + n * 4u);
}
void set_eax(X86 *c, uint32_t v) { c->r[R_EAX] = v; }
"""

MAIN = r"""
static void put_w(uint32_t p, const char *ascii) {
    for (uint32_t i = 0;; ++i) {
        const uint8_t ch = static_cast<uint8_t>(ascii[i]);
        wr16(p + i * 2u, ch);
        if (!ch) break;
    }
}

static uint32_t call3(void (*fn)(X86 *), uint32_t a0, uint32_t a1, uint32_t a2 = 0) {
    X86 c{};
    constexpr uint32_t sp = 4096u;
    wr32(sp, 0x12345678u);
    wr32(sp + 4u, a0);
    wr32(sp + 8u, a1);
    wr32(sp + 12u, a2);
    c.r[R_ESP] = sp;
    fn(&c);
    return c.r[R_EAX];
}

int main() {
    put_w(100u, "AB");
    for (uint32_t i = 0; i < 6; ++i) wr16(200u + i * 2u, 0xccccu);
    assert(call3(crt_wcsncpy, 200u, 100u, 5u) == 200u);
    assert(rd16(200u) == 'A');
    assert(rd16(202u) == 'B');
    assert(rd16(204u) == 0);
    assert(rd16(206u) == 0);
    assert(rd16(208u) == 0);
    assert(rd16(210u) == 0xccccu);

    put_w(300u, "ABCDE");
    for (uint32_t i = 0; i < 5; ++i) wr16(350u + i * 2u, 0xddddu);
    assert(call3(crt_wcsncpy, 350u, 300u, 3u) == 350u);
    assert(rd16(350u) == 'A' && rd16(352u) == 'B' && rd16(354u) == 'C');
    assert(rd16(356u) == 0xddddu);

    put_w(500u, "abca");
    // UTF-16 wcsncmp compares count *code units*, not host wchar_t bytes.
    put_w(1000u, "Alpha");
    put_w(1100u, "Alphb");
    assert(call3(crt_wcsncmp, 1000u, 1100u, 4u) == 0u);
    assert(static_cast<int32_t>(call3(crt_wcsncmp, 1000u, 1100u, 5u)) < 0);
    assert(static_cast<int32_t>(call3(crt_wcsncmp, 1100u, 1000u, 5u)) > 0);
    assert(call3(crt_wcsncmp, 1000u, 1100u, 0u) == 0u);
    put_w(1150u, "Alpha");
    assert(call3(crt_wcsncmp, 1000u, 1150u, 64u) == 0u);
    wr16(1200u, 0x8000u); wr16(1202u, 0u);
    wr16(1250u, 0x7fffu); wr16(1252u, 0u);
    assert(static_cast<int32_t>(call3(crt_wcsncmp, 1200u, 1250u, 2u)) > 0);
    assert(static_cast<int32_t>(call3(crt_wcsncmp, 0u, 1250u, 1u)) < 0);
    assert(call3(crt_wcsrchr, 500u, 'a') == 506u);
    assert(call3(crt_wcsrchr, 500u, 0u) == 508u);
    assert(call3(crt_wcsrchr, 500u, 'z') == 0u);

    put_w(700u, "hello");
    put_w(800u, "xo");
    put_w(850u, "qz");
    assert(call3(crt_wcspbrk, 700u, 800u) == 708u);
    assert(call3(crt_wcspbrk, 700u, 850u) == 0u);
    assert(call3(crt_wcspbrk, 0u, 850u) == 0u);
    return 0;
}
"""


def test_reached_wide_crt_helpers_match_windows_utf16_semantics(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler available")

    text = COMPAT.read_text()
    start = text.index(BEGIN)
    end = text.index(END, start)
    source = tmp_path / "wide_crt.cpp"
    binary = tmp_path / "wide_crt"
    source.write_text(HARNESS + "\n" + text[start:end] + "\n" + MAIN)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
