"""Native differential regression against pinned recomp-kit's gm_str behavior."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "runtime" / "reflex_crt_fast_strings.h"
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"

HARNESS = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <random>
#include <string>
#include <vector>
#include "reflex_crt_fast_strings.h"

constexpr uint32_t GUEST_SIZE = 4096u;
std::vector<uint8_t> mem(GUEST_SIZE);

std::string reference(uint32_t p, size_t cap = 0x8000u) {
    if (p == 0) return {};
    std::string out;
    for (size_t i = 0; i < cap && static_cast<uint64_t>(p) + i < GUEST_SIZE; ++i) {
        const char ch = char(mem[p + i]);
        if (!ch) break;
        out.push_back(ch);
    }
    return out;
}
int main() {
    std::mt19937 rng(0xBADDEC0Du);
    for (auto &b : mem) b = static_cast<uint8_t>(rng() % 256u);
    mem[0] = 'X';
    mem[1] = '\0';
    mem[10] = 0x80u;
    mem[11] = 0xffu;
    mem[12] = 0;
    mem[20] = 0x80u;
    mem[21] = 0xfeu;
    mem[22] = 0;
    mem[GUEST_SIZE - 1] = 0x81u;

    const std::vector<uint32_t> edges = {
        0u, 1u, 10u, 20u, 31u, GUEST_SIZE - 2u,
        GUEST_SIZE - 1u, GUEST_SIZE, GUEST_SIZE + 100u, 0xffffffffu
    };
    for (size_t cap : {0u, 1u, 2u, 16u, 100u, 0x8000u}) {
        for (uint32_t a : edges) {
            const auto expected = reference(a, cap);
            assert(reflex_crt_fast::bounded_length(mem.data(), GUEST_SIZE, a, cap)
                   == expected.size());
            for (uint32_t b : edges) {
                const auto rhs = reference(b, cap);
                const int old_rc = expected < rhs ? -1 : (expected > rhs ? 1 : 0);
                assert(reflex_crt_fast::bounded_compare(
                           mem.data(), GUEST_SIZE, a, b, cap) == old_rc);
            }
        }
        for (int i = 0; i < 2500; ++i) {
            const uint32_t a = rng() % (GUEST_SIZE + 4);
            const uint32_t b = rng() % (GUEST_SIZE + 4);
            const auto lhs = reference(a, cap), rhs = reference(b, cap);
            const int old_rc = lhs < rhs ? -1 : lhs > rhs ? 1 : 0;
            assert(reflex_crt_fast::bounded_length(mem.data(), GUEST_SIZE, a, cap)
                   == lhs.size());
            assert(reflex_crt_fast::bounded_compare(
                       mem.data(), GUEST_SIZE, a, b, cap) == old_rc);
        }
    }

    // A NUL-free buffer exercises arena truncation without OOB reads.
    std::fill(mem.begin(), mem.end(), uint8_t('Q'));
    assert(reflex_crt_fast::bounded_length(mem.data(), GUEST_SIZE, GUEST_SIZE - 1u)
           == 1u);
    assert(reflex_crt_fast::bounded_length(mem.data(), GUEST_SIZE, 1u) == 4095u);
    assert(reflex_crt_fast::bounded_compare(
               mem.data(), GUEST_SIZE, 1u, 2u) > 0);

    assert(reflex_crt_fast::bounded_length(nullptr, GUEST_SIZE, 12u) == 0u);
    return 0;
}
"""


def test_crt_guest_strings_exactly_match_reference_without_allocations(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    path = tmp_path / "fast_crt_strings.cpp"
    binary = tmp_path / "fast_crt_strings"
    path.write_text(HARNESS)
    subprocess.run(
        [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(path), "-o", str(binary)],
        check=True, text=True, capture_output=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_optimized_crt_path_remains_explicitly_opt_in():
    code = COMPAT.read_text()
    assert '#include "reflex_crt_fast_strings.h"' in code
    assert 'std::getenv("REFLEX_FAST_CRT_STRINGS")' in code
    assert "reflex_crt_fast::bounded_compare(" in code
    assert "reflex_crt_fast::bounded_length(" in code
    assert "const std::string a = gm_str(lhs), b = gm_str(rhs);" in code
