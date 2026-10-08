"""Compile real clean-room D3DX QueryInterface functions against guest memory."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"

HEADER = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <unordered_map>

constexpr uint32_t GUEST_SIZE = 4096;
uint8_t guest[GUEST_SIZE] = {};
uint8_t *g_mem = guest;
struct X86 {
    uint32_t args[3] = {};
    uint32_t eax = 0xffffffffu;
};
uint32_t arg(X86 *c, int n) { return c->args[n]; }
void set_eax(X86 *c, uint32_t eax) { c->eax = eax; }
bool gm_valid(uint32_t addr, uint32_t size) {
    return addr < GUEST_SIZE && size <= GUEST_SIZE - addr;
}
uint32_t rd32(uint32_t addr) {
    assert(gm_valid(addr, 4));
    uint32_t n = 0;
    memcpy(&n, g_mem + addr, 4);
    return n;
}
void wr32(uint32_t addr, uint32_t n) {
    assert(gm_valid(addr, 4));
    memcpy(g_mem + addr, &n, 4);
}
struct ReflexConstantTable { uint32_t refs = 1; };
std::mutex g_d3dx_ctab_mutex;
std::unordered_map<uint32_t, ReflexConstantTable> g_tables;
ReflexConstantTable *d3dx_table(uint32_t id) {
    auto it = g_tables.find(id);
    return it == g_tables.end() ? nullptr : &it->second;
}
constexpr uint32_t kNoInterface = 0x80004002u;
"""

TAIL = r"""
static void iid(uint32_t address, const uint8_t *bytes) {
    memcpy(g_mem + address, bytes, 16);
}
int main() {
    X86 c;
    const uint32_t object = 256, iid_ptr = 128, out = 384;
    wr32(object + 4, 1);
    c.args[0] = object;
    c.args[1] = iid_ptr;
    c.args[2] = out;

    iid(iid_ptr, kIidIUnknown);
    d3dx_buffer_query_interface(&c);
    assert(c.eax == 0 && rd32(out) == object && rd32(object + 4) == 2);

    iid(iid_ptr, kIidD3dxBuffer);
    d3dx_buffer_query_interface(&c);
    assert(c.eax == 0 && rd32(object + 4) == 3);

    iid(iid_ptr, kIidD3dxConstantTable43);
    d3dx_buffer_query_interface(&c);
    assert(c.eax == 0x80004002u && rd32(out) == 0);
    assert(rd32(object + 4) == 3);

    memset(g_mem + iid_ptr, 0xab, 16);
    d3dx_buffer_query_interface(&c);
    assert(c.eax == 0x80004002u && rd32(out) == 0);

    c.args[2] = 0;
    d3dx_buffer_query_interface(&c);
    assert(c.eax == 0x80004003u);

    c.args[0] = 512;
    c.args[2] = out;
    g_tables.emplace(512, ReflexConstantTable{1});
    iid(iid_ptr, kIidD3dxBuffer);
    d3dx_ctab_query_interface(&c);
    assert(c.eax == 0 && rd32(out) == 512 && g_tables.at(512).refs == 2);

    iid(iid_ptr, kIidD3dxConstantTable43);
    d3dx_ctab_query_interface(&c);
    assert(c.eax == 0 && g_tables.at(512).refs == 3);

    memset(g_mem + iid_ptr, 0x13, 16);
    d3dx_ctab_query_interface(&c);
    assert(c.eax == 0x80004002u && rd32(out) == 0);
    assert(g_tables.at(512).refs == 3);
    return 0;
}
"""


def portion(text, start, end):
    a = text.index(start)
    b = text.index(end, a + len(start))
    assert b > a
    return text[a:b]


def test_com_query_interface_real_bridge(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no native C++ compiler")
    text = COMPAT.read_text()
    iids = portion(text, "static const uint8_t kIidIUnknown[16] =",
                   "uint32_t g_d3dx_buffer_vtable = 0;")
    buffer_fn = portion(text, "void d3dx_buffer_query_interface(X86 *c) {",
                        "void d3dx_buffer_addref(X86 *c) {")
    ctab_fn = portion(text, "void d3dx_ctab_query_interface(X86 *c) {",
                      "void d3dx_ctab_addref(X86 *c) {")
    cpp = tmp_path / "test_d3dx_iids.cpp"
    binary = tmp_path / "test_d3dx_iids"
    cpp.write_text(HEADER + iids + buffer_fn + ctab_fn + TAIL)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(cpp), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
