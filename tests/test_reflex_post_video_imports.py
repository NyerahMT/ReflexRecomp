"""Regression coverage for post-intro guest CRT and FMOD bridge imports."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include "reflex_crt_fast_strings.h"

int main() {
    std::vector<uint8_t> mem(160, 0xcc);
    auto write = [&](uint32_t at, const char *value) {
        std::memcpy(mem.data() + at, value, std::strlen(value) + 1);
    };
    write(10, "Atlas/Audio/intro.bik");
    write(60, "atLAS/audio/INTRO.BIK");
    using reflex_crt_fast::bounded_ncompare;
    using reflex_crt_fast::bounded_strrchr;
    assert(bounded_ncompare(mem.data(), mem.size(), 10, 60, 0) == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 10, 60, 1) < 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 10, 60, 5, true) == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 10, 60, 64, true) == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 10, 60, 64) < 0);
    write(90, "cat"); write(100, "caterpillar");
    assert(bounded_ncompare(mem.data(), mem.size(), 90, 100, 3) == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 90, 100, 4) < 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 100, 90, 4) > 0);
    assert(bounded_strrchr(mem.data(), mem.size(), 10, '/') == 21u);
    assert(bounded_strrchr(mem.data(), mem.size(), 10, 'x') == 0);
    assert(bounded_strrchr(mem.data(), mem.size(), 90, 0) == 93u);
    assert(bounded_strrchr(mem.data(), mem.size(), 0, 'c') == 0);
    assert(bounded_strrchr(mem.data(), mem.size(), 159, 0) == 0);
    mem[150] = 0x80; mem[151] = 0;
    mem[155] = 0x7f; mem[156] = 0;
    assert(bounded_ncompare(mem.data(), mem.size(), 150, 155, 2) > 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 150, 155, 2, true) > 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 0, 999u, 0) == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 0, 90, 2) < 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 90, 999u, 2) > 0);
    mem[158] = 'z'; mem[159] = 'z';
    assert(bounded_strrchr(mem.data(), mem.size(), 158, 'z') == 0);
    assert(bounded_ncompare(mem.data(), mem.size(), 158, 90, 4) > 0);
    return 0;
}
"""


def test_narrow_guest_crt_strncmp_strnicmp_strrchr(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "guest_crt_boot.cpp"
    executable = tmp_path / "guest_crt_boot"
    source.write_text(HARNESS)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I",
         str(ROOT / "runtime"), str(source), "-o", str(executable)],
        check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)


def test_new_imports_use_correct_guest_abi_and_initialized_fmod_outputs():
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    expected = (
        '"MSVCR90.dll", "strncmp", ARGC_CDECL, crt_strncmp',
        '"MSVCR90.dll", "_strnicmp", ARGC_CDECL, crt_strnicmp',
        '"MSVCR90.dll", "strrchr", ARGC_CDECL, crt_strrchr',
        '"MSVCR90.dll", "_vswprintf_c_l", ARGC_CDECL, crt_vswprintf_c_l',
        '"?set3DSettings@System@FMOD@@QAG?AW4FMOD_RESULT@@MMM@Z"',
        '"?get3DSettings@System@FMOD@@QAG?AW4FMOD_RESULT@@PAM00@Z"',
    )
    assert all(text in code for text in expected)
    assert 'g_fmod_3d_bits[3] = {0x3f800000u' in code
    assert 'if (ptr && !gm_valid(ptr, 4))' in code
    assert 'g_fmod_3d_bits[i] = arg(c, i + 1u)' in code
    assert 'wr32(outputs[i], g_fmod_3d_bits[i])' in code
    assert 'arg(c, 2), arg(c, 4)' in code


def test_fmod_event_system_load_slot_nine_has_valid_abi_and_no_fake_success():
    """The original worker at 008065b7 calls the previously absent vtable slot 9.

    The FMOD bank loader must be a callable 4-argument stdcall shim, and
    until real FEV decoding exists it must clear its project and fail,
    rather than advertise success with an invalid audio project.
    """
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    assert "void fmod_event_system_load(X86 *c)" in code
    assert "const uint32_t filename = arg(c, 1);" in code
    assert "const uint32_t info = arg(c, 2);" in code
    assert "const uint32_t out = arg(c, 3);" in code
    assert "if (!out || !gm_valid(out, 4))" in code
    assert "wr32(out, 0);" in code
    assert "if (info && (!gm_valid(info, 24) || rd32(info) != 24u))" in code
    assert "const uint32_t vt = heap_alloc(10 * 4, true, 16);" in code
    vtable = code.split("uint32_t fmod_event_system_vtable()", 1)[1]
    entries = vtable.split("} methods[] = {", 1)[1].split("};", 1)[0]
    assert entries.count('{"FMOD::EventSystem::') == 10
    assert entries.splitlines()[9].strip() == (
        '{"FMOD::EventSystem::load", 4, fmod_event_system_load},'
    )
    assert "for (uint32_t i = 0; i < 10; ++i)" in vtable
    handler = code.split("void fmod_event_system_load(X86 *c)", 1)[1].split(
        "uint32_t fmod_event_system_vtable()", 1)[0]
    assert "set_eax(c, 1); // Nonzero FMOD_RESULT" in handler
    assert "set_eax(c, 0);" not in handler
    assert "return;" in handler
