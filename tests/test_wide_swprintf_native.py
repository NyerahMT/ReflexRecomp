"""Native, asset-free regression tests for Reflex's MSVCR90 swprintf_s shim."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "runtime" / "reflex_crt_wide_format.h"
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"

HARNESS = r"""
#include "reflex_crt_wide_format.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

static std::vector<uint8_t> mem(16384u);
static void put16(uint32_t p, uint16_t x) {
    std::memcpy(mem.data() + p, &x, 2u);
}
static uint16_t get16(uint32_t p) {
    uint16_t x;
    std::memcpy(&x, mem.data() + p, 2u);
    return x;
}
static void put32(uint32_t p, uint32_t x) {
    std::memcpy(mem.data() + p, &x, 4u);
}
static void put_w(uint32_t p, const char* text) {
    size_t i = 0;
    do { put16(p + 2u * i, static_cast<uint8_t>(text[i])); }
    while (text[i++] != '\0');
}
static void put_a(uint32_t p, const char* text) {
    std::memcpy(mem.data() + p, text, std::strlen(text) + 1u);
}
static std::string get_w(uint32_t p) {
    std::string out;
    for (size_t i = 0; i < 512; ++i) {
        const uint16_t ch = get16(p + i * 2u);
        if (!ch) return out;
        assert(ch < 128u);
        out.push_back(static_cast<char>(ch));
    }
    assert(false && "unterminated wide string");
    return {};
}
static int fmt(uint32_t count, uint32_t pattern = 100u) {
    return reflex_crt::guest_swprintf_s(
        mem.data(), static_cast<uint32_t>(mem.size()),
        400u, count, pattern, 900u);
}

int main() {
    put_w(100, "Name:%s Code:%08X %%");
    put_w(300, "Reflex");
    put32(900, 300u);
    put32(904, 0xF2u);
    const std::string expected = "Name:Reflex Code:000000F2 %";
    assert(fmt(128) == static_cast<int>(expected.size()));
    assert(get_w(400) == expected);

    put_w(100, "i=%d u=%I64u");
    put32(900, static_cast<uint32_t>(-42));
    put32(904, 0xffffffffu);
    put32(908, 0x00000001u);
    assert(fmt(128) == static_cast<int>(std::strlen("i=-42 u=8589934591")));
    assert(get_w(400) == "i=-42 u=8589934591");

    put_w(100, "[%-6.3ls][%S][%hs]");
    put_w(300, "Reflex");
    put_a(350, "Win");
    put_a(360, "x86");
    put32(900, 300u);
    put32(904, 350u);
    put32(908, 360u);
    assert(fmt(128) > 0);
    assert(get_w(400) == "[Ref   ][Win][x86]");

    put_w(100, "ABCD");
    assert(fmt(5) == 4);
    assert(get_w(400) == "ABCD");
    assert(fmt(4) == -1);
    assert(get16(400) == 0u);
    assert(fmt(0) == -1);
    assert(fmt(50000u) == -1);
    assert(fmt(100u, static_cast<uint32_t>(mem.size()) - 1u) == -1);

    put_w(100, "%s");
    put32(900, 0xffffff00u);
    assert(fmt(128) == -1);
    assert(get16(400) == 0u);
    put_w(100, "%f");
    assert(fmt(128) == -1);  // Fail closed on unsupported conversion.
    assert(get16(400) == 0u);
    put_w(100, "literal");
    assert(reflex_crt::guest_swprintf_s(mem.data(), mem.size(),
        400, 128, 100, 0xffffff00u) == 7); // no varargs read
    return 0;
}
"""


def test_swprintf_s_utf16_native_semantics(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler available")
    cpp = tmp_path / "test_swprintf.cpp"
    binary = tmp_path / "test_swprintf"
    cpp.write_text(HARNESS)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(cpp), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_swprintf_s_registered_cdecl():
    compat = COMPAT.read_text()
    assert '#include "reflex_crt_wide_format.h"' in compat
    assert 'reflex_crt::guest_swprintf_s(g_mem, GUEST_SIZE' in compat
    assert '{"MSVCR90.dll", "swprintf_s", ARGC_CDECL, crt_swprintf_s}' in compat
