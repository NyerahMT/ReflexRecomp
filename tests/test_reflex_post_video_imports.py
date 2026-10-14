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
    assert "const uint32_t vt = heap_alloc(41 * 4, true, 16);" in code
    vtable = code.split("uint32_t fmod_event_system_vtable()", 1)[1]
    entries = vtable.split("} methods[] = {", 1)[1].split("};", 1)[0]
    assert entries.count('{"FMOD::EventSystem::') == 41
    assert entries.strip().splitlines()[9].strip() == (
        '{"FMOD::EventSystem::load", 4, fmod_event_system_load},'
    )
    assert "for (uint32_t i = 0; i < 41; ++i)" in vtable
    handler = code.split("void fmod_event_system_load(X86 *c)", 1)[1].split(
        "uint32_t fmod_event_system_vtable()", 1)[0]
    assert "set_eax(c, 1); // Nonzero FMOD_RESULT" in handler
    assert "set_eax(c, 0);" not in handler
    assert "return;" in handler


def test_fmod_sound_imports_do_not_return_false_success_or_leak_stack_words():
    """The 2026-10-13 original-game run reached both unsupported FMOD imports."""
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    create_symbol = '"?createSound@System@FMOD@@QAG?AW4FMOD_RESULT@@PBDIPAUFMOD_CREATESOUNDEXINFO@@PAPAVSound@2@@Z"'
    count_symbol = '"?getNumSubSounds@Sound@FMOD@@QAG?AW4FMOD_RESULT@@PAH@Z"'
    assert create_symbol in code
    assert count_symbol in code
    assert '5, fmod_system_create_sound}' in code
    assert '2, fmod_sound_get_num_sub_sounds}' in code

    create = code.split("void fmod_system_create_sound(X86 *c)", 1)[1].split(
        "void fmod_sound_get_num_sub_sounds(X86 *c)", 1)[0]
    assert "arg(c, 1)" in create
    assert "arg(c, 2)" in create
    assert "arg(c, 3)" in create
    assert "arg(c, 4)" in create
    assert "if (!out || !gm_valid(out, 4))" in create
    assert "wr32(out, 0);" in create
    assert "set_eax(c, 1);" in create
    assert "set_eax(c, 0);" not in create
    assert r'unsupported\n"' in create

    count = code.split("void fmod_sound_get_num_sub_sounds(X86 *c)", 1)[1].split(
        "void fmod_system_get_master_channel_group(X86 *c)", 1)[0]
    assert "arg(c, 0)" in count
    assert "arg(c, 1)" in count
    assert "if (!count_out || !gm_valid(count_out, 4))" in count
    assert "wr32(count_out, 0);" in count
    assert "set_eax(c, 1);" in count
    assert "set_eax(c, 0);" not in count
    assert r'unsupported\n"' in count


def test_fmod_eventsystem_has_correct_designer_4x_slot_order_and_preload_fsb_abi():
    """The 008067fb call dispatches EventSystem slot 38, not a Sound method."""
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    vtable = code.split("uint32_t fmod_event_system_vtable()", 1)[1]
    entries = vtable.split("} methods[] = {", 1)[1].split("};", 1)[0]
    import re
    methods = re.findall(
        r'\{"FMOD::EventSystem::(\w+)",\s*(\d+),\s*(\w+)\}', entries
    )
    assert len(methods) == 41, "Every guest vtable slot must have a handler"
    expected = {
        0: ("init", "5"),
        7: ("getSystemObject", "2"),
        9: ("load", "4"),
        10: ("unload", "1"),
        18: ("getGroup", "4"),
        19: ("getEvent", "4"),
        34: ("set3DListenerAttributes", "6"),
        37: ("getUserData", "2"),
        38: ("preloadFSB", "4"),
        39: ("unloadFSB", "3"),
        40: ("getMemoryInfo", "5"),
    }
    for slot, (name, argc) in expected.items():
        assert methods[slot][:2] == (name, argc), (slot, methods[slot])
    assert methods[38][2] == "fmod_event_system_preload_fsb"
    assert methods[39][2] == "fmod_event_system_unload_fsb"
    for entry in methods:
        assert re.search(
            rf"\bvoid\s+{entry[2]}\(X86\s*\*c\)",
            code,
        ), entry

    handler = code.split("void fmod_event_system_preload_fsb(X86 *c)", 1)[1].split(
        "void fmod_event_system_unload_fsb(X86 *c)", 1
    )[0]
    assert "const uint32_t filename = arg(c, 1);" in handler
    assert "const uint32_t stream_instance = arg(c, 2);" in handler
    assert "const uint32_t sound = arg(c, 3);" in handler
    assert "filename && gm_valid(filename, 1)" in handler
    assert "set_eax(c, 1);" in handler
    assert "set_eax(c, 0);" not in handler



def test_fmod_system_spatial_exports_have_exact_msvc_32bit_abi():
    """Post-D3DX original game hit these three unknown-arity Ex member calls.

    EventSystem virtual setters are separate; these are the nonvirtual System
    exports from the DLL and include this in the guest's stack arguments.
    """
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    symbols = (
        ('?setReverbAmbientProperties@System@FMOD@@QAG?AW4FMOD_RESULT@@PAUFMOD_REVERB_PROPERTIES@@@Z',
         2, 'fmod_system_set_reverb_ambient_properties'),
        ('?set3DNumListeners@System@FMOD@@QAG?AW4FMOD_RESULT@@H@Z',
         2, 'fmod_system_set_3d_num_listeners'),
        ('?set3DListenerAttributes@System@FMOD@@QAG?AW4FMOD_RESULT@@HPBUFMOD_VECTOR@@000@Z',
         6, 'fmod_system_set_3d_listener_attributes'),
    )
    for symbol, argc, fn in symbols:
        assert code.count('"' + symbol + '"') == 1
        assert f'{argc}, {fn}' in code
        assert f'void {fn}(X86 *c)' in code

    listener = code.split('void fmod_system_set_3d_listener_attributes(X86 *c)', 1)[1]
    listener = listener.split('void fmod_system_set_reverb_ambient_properties(X86 *c)', 1)[0]
    for i in range(1, 6):
        assert f'arg(c, {i})' in listener
    assert 'gm_valid(ptr, 12u)' in listener
    assert 'index >= g_fmod_listener_count' in listener
    assert 'rd32(vectors[v] + lane * 4u)' in listener
    assert 'set_eax(c, 0)' in listener

    count = code.split('void fmod_system_set_3d_num_listeners(X86 *c)', 1)[1]
    count = count.split('void fmod_system_set_3d_listener_attributes(X86 *c)', 1)[0]
    assert 'count < 1u || count > 8u' in count
    assert 'g_fmod_listener_count = count;' in count

    reverb = code.split('void fmod_system_set_reverb_ambient_properties(X86 *c)', 1)[1]
    reverb = reverb.split('void fmod_system_get_3d_settings(X86 *c)', 1)[0]
    assert 'const uint32_t props = arg(c, 1);' in reverb
    assert 'gm_valid(props, 4u)' in reverb
    assert 'set_eax(c, 0)' in reverb



def test_original_game_crt_math_and_tokenizer_imports_are_cdecl_with_guest_state():
    """Run 162 reached these CRT names before the FMOD spatial ABI failure."""
    code = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    expected = (
        ('ceil', 'crt_ceil'),
        ('__libm_sse2_acos', 'crt_libm_sse2_acos'),
        ('__libm_sse2_pow', 'crt_libm_sse2_pow'),
        ('strtok', 'crt_strtok'),
    )
    for export, fn in expected:
        assert code.count(f'"{export}", ARGC_CDECL, {fn}') == 1
        assert f'void {fn}(X86 *c)' in code
    # SSE2 libm internal functions do not return floating point values in ST0.
    acos = code.split('void crt_libm_sse2_acos(X86 *c)', 1)[1].split(
        'void crt_libm_sse2_pow(X86 *c)', 1)[0]
    assert 'xmm_set_f64(c, 0, std::acos(xmm_f64(c, 0)))' in acos
    power = code.split('void crt_libm_sse2_pow(X86 *c)', 1)[1].split(
        'void crt_libm_sse2_expf(X86 *c)', 1)[0]
    assert 'std::pow(base, exponent)' in power
    assert 'xmm_f64(c, 1)' in power
    # Standard ceil is a stack-argument x87-return function on 32-bit x86.
    ceil = code.split('void crt_ceil(X86 *c)', 1)[1].split(
        'void crt_strtok(X86 *c)', 1)[0]
    assert 'rdf64(esp + 4u)' in ceil
    assert 'fpush(c, std::ceil(' in ceil
    tokenize = code.split('void crt_strtok(X86 *c)', 1)[1].split(
        'void crt_atof(X86 *c)', 1)[0]
    assert 'static thread_local uint32_t continuation' in tokenize
    assert 'gm_str(delims, 32768u)' in tokenize
    assert 'wr8(current, 0)' in tokenize
    assert 'set_eax(c, token)' in tokenize
    assert 'gm_valid(current, 1u)' in tokenize
