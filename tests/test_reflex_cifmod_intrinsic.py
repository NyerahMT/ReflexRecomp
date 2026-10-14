"""Original Reflex MSVCR90 _CIfmod x86 x87 guest-ABI regression tests.

The compiler-intrinsic arguments are in x87 ST0/ST1, not guest ESP and
not SSE XMM0/XMM1. Compile the actual shim body with a minimal guest-state
fixture so wrong result ordering / stack bookkeeping fails before runtime.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "runtime" / "reflex_compat.cpp").read_text()


def test_cifmod_is_registered_as_cdecl_with_a_real_handler():
    registration = '{"MSVCR90.dll", "_CIfmod", ARGC_CDECL, crt_cifmod}'
    assert SOURCE.count(registration) == 1
    assert SOURCE.count("void crt_cifmod(X86 *c)") == 1
    assert "std::fmod(c->st[dividend_slot], c->st[divisor_slot])" in SOURCE


FIXTURE = r"""
#include <cassert>
#include <cmath>
#include <cstdint>

struct X86 {
    uint32_t fpu_top = 0;
    uint16_t fpu_tag = 0xffffu;
    uint16_t fpu_sw = 0;
    double st[8] = {};
    uint64_t st_bits[8] = {};
    uint8_t st_exact[8] = {};
    uint32_t eax = 0xffffffffu;
};
void set_eax(X86 *c, uint32_t value) { c->eax = value; }

void prepare(X86 *c, uint32_t top, double divisor, double dividend) {
    *c = X86{};
    c->fpu_top = top;
    uint32_t d = top & 7u, n = (top + 1u) & 7u;
    c->fpu_tag &= uint16_t(~((3u << (d * 2u)) | (3u << (n * 2u))));
    c->fpu_sw = uint16_t((top & 7u) << 11);
    c->st[d] = divisor;
    c->st[n] = dividend;
    c->st_bits[n] = 1234u;
    c->st_exact[n] = 1u;
}
"""

TEST_CASES = r"""
int main() {
    X86 c;
    prepare(&c, 6u, 3.0, -10.0);
    crt_cifmod(&c);
    assert(c.fpu_top == 7u);
    assert(c.st[7] == -1.0);
    assert(((c.fpu_tag >> (6u * 2u)) & 3u) == 3u);
    assert(((c.fpu_tag >> (7u * 2u)) & 3u) != 3u);
    assert(c.st_bits[7] == 0 && c.st_exact[7] == 0);
    assert(((c.fpu_sw >> 11) & 7u) == 7u);
    assert(c.eax == 0u);

    prepare(&c, 7u, -3.0, 10.0);
    crt_cifmod(&c);
    assert(c.fpu_top == 0u);
    assert(c.st[0] == 1.0);
    assert(((c.fpu_sw >> 11) & 7u) == 0u);

    prepare(&c, 2u, 3.0, -9.0);
    crt_cifmod(&c);
    assert(c.st[3] == 0.0 && std::signbit(c.st[3]));

    prepare(&c, 4u, 0.0, 10.0);
    crt_cifmod(&c);
    assert(std::isnan(c.st[5]));

    // Missing operand must not fabricate a value or alter x87 state.
    prepare(&c, 3u, 4.0, 7.0);
    c.fpu_tag |= uint16_t(3u << (3u * 2u));
    const uint32_t top = c.fpu_top;
    const uint16_t tag = c.fpu_tag;
    crt_cifmod(&c);
    assert(c.fpu_top == top && c.fpu_tag == tag);
}
"""


def test_cifmod_native_guest_x87_contract(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("No native C++ compiler installed")
    implementation = SOURCE.split("void crt_cifmod(X86 *c) {", 1)[1].split(
        "\nvoid crt_strchr(X86 *c) {", 1
    )[0]
    code = FIXTURE + "\nvoid crt_cifmod(X86 *c) {" + implementation + TEST_CASES
    path = tmp_path / "guest_cifmod.cpp"
    binary = tmp_path / "guest_cifmod"
    path.write_text(code)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(path), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
