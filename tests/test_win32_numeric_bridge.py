"""Native width-compatibility tests for the clean-room MSVCR integer bridge."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = r"""
#include "reflex_crt_numeric.h"
#include <cassert>
#include <cerrno>
#include <climits>
#include <cstdint>
#include <string>

int main() {
    using namespace reflex_crt;
    auto signed_parse = [](const std::string &s, int base = 10) {
        return parse_signed32(s, base);
    };
    auto unsigned_parse = [](const std::string &s, int base = 10) {
        return parse_unsigned32(s, base);
    };
    assert(signed_parse("2147483647").value == 0x7fffffffu);
    errno = 0;
    assert(signed_parse("2147483648").value == 0x7fffffffu);
    assert(errno == ERANGE);
    errno = 0;
    assert(signed_parse("-2147483649").value == 0x80000000u);
    assert(errno == ERANGE);
    errno = 0;
    assert(signed_parse("-92233720368547758089999").value == 0x80000000u);
    assert(errno == ERANGE);
    assert(signed_parse("  -0x80suffix", 0).value == 0xffffff80u);
    assert(signed_parse("  -0x80suffix", 0).consumed == 7);
    assert(signed_parse("x").consumed == 0);
    assert(unsigned_parse("4294967295").value == UINT32_MAX);
    errno = 0;
    assert(unsigned_parse("4294967296").value == UINT32_MAX);
    assert(errno == ERANGE);
    assert(unsigned_parse("-1").value == UINT32_MAX);
    assert(unsigned_parse("-2").value == UINT32_MAX - 1);
    assert(unsigned_parse("  -0x10tail", 0).value == 0xfffffff0u);
    assert(unsigned_parse("  -0x10tail", 0).consumed == 7);
    assert(unsigned_parse("-").consumed == 0);
    assert(unsigned_parse("  -wrong").consumed == 0);
    assert(unsigned_parse("+12suffix").consumed == 3);
    assert(!valid_base(1) && !valid_base(37));
    assert(valid_base(0) && valid_base(2) && valid_base(36));
    return 0;
}
"""


def test_native_win32_integer_width_and_overflow(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler")
    source = tmp_path / "crt_numeric.cpp"
    executable = tmp_path / "crt_numeric"
    source.write_text(SOURCE)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(source), "-o", str(executable)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
