"""Compile and exercise the actual Reflex MSVCP90 C-string constructor.

The resource-finalizer bug exposed that Reflex's VS2008 basic_string<char>
uses a 28-byte object with a four-byte container-base prefix. Exercise the
real constructor implementation from runtime/reflex_compat.cpp so future
changes cannot silently shift the SSO buffer back to offset zero.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"
BEGIN = "constexpr uint32_t kMsvcpStringObjectSize = 28u;"
END = "bool msvcp_string_assign_value(uint32_t self, const std::string &value) {"

HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

constexpr uint32_t GUEST_SIZE = 16384u;
std::vector<uint8_t> guest(GUEST_SIZE);
uint8_t *g_mem = guest.data();
uint32_t next_alloc = 8192u;

enum { R_EAX = 0, R_ECX = 1, R_ESP = 4 };
struct X86 { uint32_t r[8] = {}; };

bool gm_valid(uint32_t p, uint32_t n) {
    return p < GUEST_SIZE && n <= GUEST_SIZE - p;
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

std::string gm_str(uint32_t p, uint32_t limit) {
    std::string out;
    for (uint32_t i = 0; i < limit && gm_valid(p + i, 1); ++i) {
        const char ch = static_cast<char>(g_mem[p + i]);
        if (!ch) break;
        out.push_back(ch);
    }
    return out;
}
uint32_t heap_alloc(uint32_t n, bool = false) {
    if (!n || !gm_valid(next_alloc, n))
        return 0;
    const uint32_t p = next_alloc;
    next_alloc += (n + 15u) & ~15u;
    return p;
}
"""

MAIN = r"""
static void place_cstr(uint32_t p, const std::string &s) {
    assert(gm_valid(p, static_cast<uint32_t>(s.size() + 1)));
    memcpy(g_mem + p, s.data(), s.size());
    g_mem[p + s.size()] = 0;
}

static void call_ctor(uint32_t self, uint32_t src) {
    X86 c{};
    constexpr uint32_t sp = 4096u;
    wr32(sp, 0x12345678u);
    wr32(sp + 4u, src);
    c.r[R_ECX] = self;
    c.r[R_ESP] = sp;
    msvcp_string_ctor_cstr(&c);
    assert(c.r[R_EAX] == self);
}

int main() {
    place_cstr(1000u, "Intro.");
    call_ctor(200u, 1000u);

    // Four-byte base prefix, then inline data, then size/capacity.
    assert(rd32(200u) == 0u);
    assert(memcmp(g_mem + 204u, "Intro.", 6) == 0);
    assert(g_mem[210u] == 0);
    assert(rd32(220u) == 6u);
    assert(rd32(224u) == 15u);
    assert(msvcp_string_data(200u) == 204u);

    const std::string long_value(40, 'R');
    place_cstr(1200u, long_value);
    call_ctor(300u, 1200u);
    const uint32_t heap = rd32(304u);
    assert(heap >= 8192u);
    assert(rd32(300u) == 0u);
    assert(rd32(320u) == long_value.size());
    assert(rd32(324u) == long_value.size());
    assert(msvcp_string_data(300u) == heap);
    assert(memcmp(g_mem + heap, long_value.data(), long_value.size()) == 0);
    assert(g_mem[heap + long_value.size()] == 0);
    return 0;
}
"""


def test_actual_cstr_constructor_uses_reflex_28_byte_layout(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler available")

    source_text = COMPAT.read_text()
    start = source_text.index(BEGIN)
    end = source_text.index(END, start)
    extracted = source_text[start:end]

    source = tmp_path / "ctor_layout.cpp"
    binary = tmp_path / "ctor_layout"
    source.write_text(HARNESS + "\n" + extracted + "\n" + MAIN)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
