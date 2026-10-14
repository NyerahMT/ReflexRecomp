"""Native, copyrighted-asset-free regression for guest-callback CRT qsort."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"
BEGIN = "// MSVCR90 qsort(base, count, width, comparator)"
END = "void crt_wcsncpy(X86 *c) {"
PREFIX = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

constexpr uint32_t GUEST_SIZE = 0x40000u;
std::vector<uint8_t> guest(GUEST_SIZE, 0);
uint8_t *g_mem = guest.data();
enum { R_EAX = 0, R_ESP = 4 };
struct X86 { uint32_t r[8] = {}; };
uint32_t inargs[4] = {};
uint32_t callback_calls = 0;
uint32_t arg(X86 *, int index) { return inargs[index]; }
void set_eax(X86 *c, uint32_t value) { c->r[R_EAX] = value; }
bool gm_valid(uint32_t address, uint32_t bytes) {
    return address < GUEST_SIZE && bytes <= GUEST_SIZE - address;
}
uint32_t get_u32(uint32_t addr) {
    assert(gm_valid(addr, 4));
    uint32_t value;
    memcpy(&value, g_mem + addr, 4);
    return value;
}
void put_u32(uint32_t addr, uint32_t value) {
    assert(gm_valid(addr, 4));
    memcpy(g_mem + addr, &value, 4);
}
uint32_t guest_call(X86 *, uint32_t fn, uint32_t lhs, uint32_t rhs) {
    assert(fn == 0x9000u);
    assert(gm_valid(lhs, 4) && gm_valid(rhs, 4));
    ++callback_calls;
    auto a = static_cast<int32_t>(get_u32(lhs));
    auto b = static_cast<int32_t>(get_u32(rhs));
    return static_cast<uint32_t>((a > b) - (a < b));
}
"""
MAIN = r"""
static void fill(uint32_t base, uint32_t width,
                 std::vector<int32_t> numbers) {
    for (uint32_t i = 0; i < numbers.size(); ++i)
        put_u32(base + i * width, static_cast<uint32_t>(numbers[i]));
}
static void sorted(uint32_t base, uint32_t width,
                   const std::vector<int32_t> &expected) {
    for (uint32_t i = 0; i < expected.size(); ++i)
        assert(static_cast<int32_t>(get_u32(base + i * width)) == expected[i]);
}
int main() {
    X86 c{};
    constexpr uint32_t base = 0x3000u;
    const std::vector<int32_t> input = {9, -2, 0, 9, 1, -7, 4, 4, 10, 3};
    inargs[0] = base;
    inargs[1] = static_cast<uint32_t>(input.size());
    inargs[2] = 4u;
    inargs[3] = 0x9000u;
    fill(base, 4, input);
    crt_qsort(&c);
    sorted(base, 4, {-7, -2, 0, 1, 3, 4, 4, 9, 9, 10});
    assert(callback_calls > 0);
    assert(c.r[R_EAX] == 0);

    // Verify element widths > 256 bytes use bounded swap chunks correctly.
    constexpr uint32_t widebase = 0x7000u;
    constexpr uint32_t wide = 524u;
    inargs[0] = widebase; inargs[1] = 4u; inargs[2] = wide;
    fill(widebase, wide, {7, -8, 2, -1});
    for (uint32_t i = 0; i < 4; ++i)
        memset(g_mem + widebase + i * wide + 4, (int)(i + 1), wide - 4);
    crt_qsort(&c);
    sorted(widebase, wide, {-8, -1, 2, 7});
    assert(g_mem[widebase + 4] == 2u);
    assert(g_mem[widebase + wide + 4] == 4u);
    assert(g_mem[widebase + 2*wide + 4] == 3u);
    assert(g_mem[widebase + 3*wide + 4] == 1u);

    // Reject invalid callback and out-of-bounds array, never dereference.
    const uint32_t called = callback_calls;
    inargs[3] = 0u;
    crt_qsort(&c);
    assert(callback_calls == called);
    inargs[3] = 0x9000u;
    inargs[0] = GUEST_SIZE - 3u;
    crt_qsort(&c);
    assert(callback_calls == called);
    inargs[1] = 0u; // Standard zero-element no-op.
    crt_qsort(&c);
    assert(callback_calls == called);
    return 0;
}
"""


def test_crt_qsort_uses_real_guest_callback_without_host_pointer_escape(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    compat = COMPAT.read_text()
    start, end = compat.index(BEGIN), compat.index(END, compat.index(BEGIN))
    source = tmp_path / "qsort.cpp"
    binary = tmp_path / "qsort"
    source.write_text(PREFIX + "\n" + compat[start:end] + "\n" + MAIN)
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(source), "-o", str(binary)],
                   capture_output=True, text=True, check=True)
    subprocess.run([str(binary)], capture_output=True, text=True, check=True)


def test_crt_qsort_export_cdecl_and_original_callback_bridge():
    compat = COMPAT.read_text()
    assert compat.count('"MSVCR90.dll", "qsort", ARGC_CDECL, crt_qsort') == 1
    qsort = compat.split(BEGIN, 1)[1].split(END, 1)[0]
    assert "guest_call(c, comparator, at(a), at(b))" in qsort
    assert "uint64_t(count) * uint64_t(width)" in qsort
    assert "gm_valid(base, static_cast<uint32_t>(bytes))" in qsort
    assert "set_eax(c, 0u)" in qsort
