"""Build and exercise the actual MSVCP90 guest-string copy implementation.

This compiles the two clean-room functions straight from reflex_compat.cpp
against a tiny guest-memory/heap fixture; tests cannot drift into an unrelated
Python reimplementation of the copied logic.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"
CONSTANTS_BEGIN = "constexpr uint32_t kMsvcpStringObjectSize = 28u;"
CONSTANTS_END = "void msvcp_string_ctor_default(X86 *c) {"
BEGIN = "uint32_t msvcp_string_data(uint32_t object) {"
END = "void msvcp_string_ctor_copy(X86 *c) {"

HARNESS_START = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <vector>
#include <string>
constexpr uint32_t GUEST_SIZE = 8192u;
std::vector<uint8_t> guest(GUEST_SIZE);
uint8_t *g_mem = guest.data();
uint32_t next_alloc = 4096u;
bool fail_alloc = false;

bool gm_valid(uint32_t address, uint32_t count) {
    return address < GUEST_SIZE && count <= GUEST_SIZE - address;
}
uint32_t rd32(uint32_t address) {
    assert(gm_valid(address, 4));
    uint32_t value;
    memcpy(&value, g_mem + address, 4);
    return value;
}
void wr32(uint32_t address, uint32_t value) {
    assert(gm_valid(address, 4));
    memcpy(g_mem + address, &value, 4);
}
uint32_t heap_alloc(uint32_t size, bool = false) {
    if (fail_alloc || !gm_valid(next_alloc, size + 16))
        return 0;
    const uint32_t result = next_alloc;
    next_alloc += (size + 15u) & ~15u;
    return result;
}
"""

HARNESS_END = r"""
static void setup_string(uint32_t address, const std::string &value) {
    assert(gm_valid(address, 28));
    memset(g_mem + address, 0, 28);
    const uint32_t n = static_cast<uint32_t>(value.size());
    if (n <= 15) {
        memcpy(g_mem + address + 4, value.data(), n);
        wr32(address + 24, 15);
    } else {
        const uint32_t data = 800;
        memcpy(g_mem + data, value.data(), n);
        g_mem[data + n] = 0;
        wr32(address + 4, data);
        wr32(address + 24, n);
    }
    wr32(address + 20, n);
}
static std::string data_at(uint32_t obj) {
    const auto data = msvcp_string_data(obj);
    return std::string(reinterpret_cast<const char*>(g_mem + data),
                       rd32(obj + 20));
}

int main() {
    setup_string(100, "hello small");
    assert(rd32(100 + 24) == 15u);
    assert(memcmp(g_mem + 100 + 4, "hello small", 11) == 0);
    assert(msvcp_string_copy_into(200, 100));
    assert(data_at(200) == "hello small");
    assert(rd32(200 + 24) == 15u);
    assert(msvcp_string_copy_into(200, 200));
    assert(data_at(200) == "hello small");

    // Regression for the resource-finalizer key that exposed the +4 layout.
    setup_string(240, "Intro.");
    assert(rd32(240) == 0u);
    assert(rd32(240 + 20) == 6u);
    assert(rd32(240 + 24) == 15u);
    assert(memcmp(g_mem + 244, "Intro.", 6) == 0);
    assert(data_at(240) == "Intro.");

    // Destination overlaps the source's small inline storage and fields.
    setup_string(300, "overlap-test");
    assert(msvcp_string_copy_into(308, 300));
    assert(data_at(308) == "overlap-test");

    const std::string large(100, 'X');
    setup_string(600, large);
    assert(msvcp_string_copy_into(700, 600));
    assert(data_at(700) == large);
    assert(rd32(700 + 24) == large.size());
    assert(rd32(700 + 4) != rd32(600 + 4));

    setup_string(1000, large);
    memset(g_mem + 1100, 0xa5, 28);
    fail_alloc = true;
    assert(!msvcp_string_copy_into(1100, 1000));
    for (unsigned i = 0; i < 28; ++i)
        assert(g_mem[1100 + i] == 0xa5);
    return 0;
}
"""


def test_native_msvcp_copy_alias_and_allocation_failure(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler available")
    content = COMPAT.read_text()
    constants_start = content.index(CONSTANTS_BEGIN)
    constants_end = content.index(CONSTANTS_END, constants_start)
    start, end = content.index(BEGIN), content.index(END)
    assert constants_start < constants_end and start < end
    source = tmp_path / "test_string.cpp"
    binary = tmp_path / "test_string"
    source.write_text(
        HARNESS_START + "\n"
        + content[constants_start:constants_end] + "\n"
        + content[start:end] + "\n"
        + HARNESS_END
    )
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
