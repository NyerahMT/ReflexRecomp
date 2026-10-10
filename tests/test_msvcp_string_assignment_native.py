"""Native regression coverage for the VS2008 std::string assignment shim."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"

PREFIX = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

constexpr uint32_t GUEST_SIZE = 32768u;
std::vector<uint8_t> guest(GUEST_SIZE);
uint8_t* g_mem = guest.data();
uint32_t next_alloc = 4096;
bool fail_alloc = false;
std::vector<uint32_t> owned, released;
bool gm_valid(uint32_t p, uint32_t n) {
    return p < GUEST_SIZE && n <= GUEST_SIZE - p;
}
uint32_t rd32(uint32_t p) {
    assert(gm_valid(p, 4));
    uint32_t v;
    memcpy(&v, g_mem + p, 4);
    return v;
}
void wr32(uint32_t p, uint32_t v) {
    assert(gm_valid(p, 4));
    memcpy(g_mem + p, &v, 4);
}
uint32_t heap_alloc(uint32_t n, bool = false) {
    if (fail_alloc || !gm_valid(next_alloc, n + 16))
        return 0;
    const uint32_t p = next_alloc;
    next_alloc += (n + 15u) & ~15u;
    owned.push_back(p);
    return p;
}
bool heap_owns(uint32_t p) {
    return std::find(owned.begin(), owned.end(), p) != owned.end()
        && std::find(released.begin(), released.end(), p) == released.end();
}
void heap_free(uint32_t p) {
    assert(heap_owns(p));
    released.push_back(p);
}
"""

SUFFIX = r"""
void setup_string(uint32_t obj, const std::string &value) {
    assert(gm_valid(obj, 24));
    memset(g_mem + obj, 0, 24);
    const uint32_t n = static_cast<uint32_t>(value.size());
    if (n <= 15) {
        memcpy(g_mem + obj, value.data(), n);
        wr32(obj + 20, 15);
    } else {
        const uint32_t buffer = heap_alloc(n + 1u);
        assert(buffer);
        memcpy(g_mem + buffer, value.data(), n);
        g_mem[buffer + n] = 0;
        wr32(obj, buffer);
        wr32(obj + 20, n);
    }
    wr32(obj + 16, n);
}
std::string value_at(uint32_t obj) {
    const uint32_t data = msvcp_string_data(obj);
    return std::string(reinterpret_cast<const char*>(g_mem + data),
                       rd32(obj + 16));
}
int main() {
    setup_string(100, "old");
    setup_string(200, "Intro.ENG");
    assert(msvcp_string_assign_from(100, 200));
    assert(value_at(100) == "Intro.ENG");

    setup_string(300, std::string(80, 'A'));
    const uint32_t old_heap = rd32(300);
    assert(msvcp_string_assign_from(300, 200));
    assert(value_at(300) == "Intro.ENG");
    assert(!heap_owns(old_heap));

    setup_string(400, "short");
    setup_string(500, std::string(90, 'B'));
    const uint32_t source_heap = rd32(500);
    assert(msvcp_string_assign_from(400, 500));
    assert(value_at(400) == std::string(90, 'B'));
    assert(rd32(400) != source_heap);
    g_mem[source_heap] = 'C';
    assert(value_at(400) == std::string(90, 'B'));

    setup_string(600, std::string(35, 'D'));
    const uint32_t previous_heap = rd32(600);
    assert(msvcp_string_assign_from(600, 500));
    assert(!heap_owns(previous_heap));
    assert(value_at(600).size() == 90);
    assert(value_at(600)[0] == 'C');

    const uint32_t self_ptr = rd32(500);
    assert(msvcp_string_assign_from(500, 500));
    assert(rd32(500) == self_ptr && heap_owns(self_ptr));

    setup_string(700, "unchanged");
    fail_alloc = true;
    assert(!msvcp_string_assign_from(700, 500));
    assert(value_at(700) == "unchanged");
    assert(!msvcp_string_assign_from(700, GUEST_SIZE - 5));
    assert(value_at(700) == "unchanged");
    return 0;
}
"""

def test_guest_string_copy_assignment(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no native compiler installed")
    source = COMPAT.read_text()
    copy = source[source.index("uint32_t msvcp_string_data(uint32_t object) {"):
                  source.index("void msvcp_string_ctor_copy(X86 *c) {")]
    assign = source[source.index("bool msvcp_string_assign_value(uint32_t self, const std::string &value) {"):
                    source.index("void msvcp_string_assign_copy(X86 *c) {")]
    cpp = tmp_path / "assignment.cpp"
    exe = tmp_path / "assignment"
    cpp.write_text(PREFIX + "\n" + copy + "\n" + assign + "\n" + SUFFIX)
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(cpp), "-o", str(exe)],
                   check=True, text=True, capture_output=True)
    subprocess.run([str(exe)], check=True, text=True, capture_output=True)
