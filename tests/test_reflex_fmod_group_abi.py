"""Native startup ABI tests for FMOD ChannelGroup and SoundGroup setters."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "runtime" / "reflex_compat.cpp"
HEADER = r"""
#include <cassert>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <mutex>

enum { R_EAX, R_ECX, R_EDX, R_EBX, R_ESP, R_EBP, R_ESI, R_EDI };
struct X86 { uint32_t r[8] = {}; };
static uint32_t args[6];
uint32_t arg(X86 *, uint32_t i) { return args[i]; }
void set_eax(X86 *c, uint32_t v) { c->r[R_EAX] = v; }
uint32_t g_fmod_channel_group = 0x10000u;
uint32_t g_fmod_sound_group = 0x20000u;
bool heap_owns(uint32_t p) { return p == 0x10000u || p == 0x20000u; }
"""
MAIN = r"""
int main() {
    X86 c{};
    args[0] = g_fmod_channel_group;
    args[1] = 1u;
    fmod_channel_group_set_mute(&c);
    assert(c.r[R_EAX] == 0 && g_fmod_master_muted);
    args[1] = 0u;
    fmod_channel_group_set_mute(&c);
    assert(c.r[R_EAX] == 0 && !g_fmod_master_muted);
    args[0] = 0x30100u;
    fmod_channel_group_set_mute(&c);
    assert(c.r[R_EAX] != 0u);
    args[0] = g_fmod_sound_group;
    float half = 0.5f;
    std::memcpy(&args[1], &half, 4);
    fmod_sound_group_set_volume(&c);
    assert(c.r[R_EAX] == 0 && g_fmod_master_sound_volume_bits == args[1]);
    args[1] = 0x7fc00000u; // nan fails, cannot poison state
    fmod_sound_group_set_volume(&c);
    assert(c.r[R_EAX] != 0 && g_fmod_master_sound_volume_bits != args[1]);
    args[1] = 0x40000000u; // 2.0f out of documented [0,1] level
    fmod_sound_group_set_volume(&c);
    assert(c.r[R_EAX] != 0);
    args[0] = g_fmod_channel_group; args[1] = 0u;
    fmod_sound_group_set_volume(&c);
    assert(c.r[R_EAX] != 0);
    return 0;
}
"""


def test_fmod_master_group_setters_native(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no native C++ compiler installed")
    code = COMPAT.read_text()
    start = code.index("// The original game configures its FMOD group state")
    end = code.index("void fmod_event_get_system_object(X86 *c)", start)
    source = tmp_path / "fmod.cpp"
    binary = tmp_path / "fmod"
    source.write_text(HEADER + "\n" + code[start:end] + "\n" + MAIN)
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(source), "-o", str(binary)],
                   capture_output=True, text=True, check=True)
    subprocess.run([str(binary)], capture_output=True, text=True, check=True)


def test_fmod_export_names_and_callee_stack_counts():
    code = COMPAT.read_text()
    for export, fn in [
        ("?setMute@ChannelGroup@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z",
         "fmod_channel_group_set_mute"),
        ("?setVolume@SoundGroup@FMOD@@QAG?AW4FMOD_RESULT@@M@Z",
         "fmod_sound_group_set_volume"),
    ]:
        assert code.count(f'"{export}"') == 1
        assert f"2, {fn}" in code
    assert '"MSVCR90.dll", "wcsncmp", ARGC_CDECL, crt_wcsncmp' in code
