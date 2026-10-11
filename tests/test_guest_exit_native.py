"""Regression tests for MSVCR90 _exit and offline Steam lifecycle exports."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "runtime" / "reflex_compat.cpp"
HEADER = ROOT / "runtime" / "reflex_crt_termination.h"


def test_quick_exit_noreturn_and_no_atexit_handlers(tmp_path):
    cxx = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if cxx is None:
        pytest.skip("C++ compiler unavailable")
    code = tmp_path / "termination.cpp"
    binary = tmp_path / "termination"
    marker = tmp_path / "atexit-marker"
    code.write_text(r'''
#include "reflex_crt_termination.h"
#include <cstdio>
#include <cstdlib>
static const char* marker;
static void handler() {
    FILE* out = std::fopen(marker, "wb");
    if (out) {
        std::fputs("called", out);
        std::fclose(out);
    }
}
int main(int argc, char** argv) {
    if (argc < 2) return 99;
    marker = argv[1];
    std::atexit(handler);
    reflex_crt::quick_exit(7);
}
''')
    subprocess.run(
        [cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "runtime"), str(code), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    done = subprocess.run([str(binary), str(marker)], capture_output=True)
    assert done.returncode == 7
    assert not marker.exists(), "_exit must not run guest atexit handlers"


def test_imports_registered_as_cdecl_and_exit_nonreturning():
    source = SRC.read_text()
    assert '#include "reflex_crt_termination.h"' in source
    assert HEADER.is_file()
    assert '[[noreturn]] void crt_quick_exit(X86 *c)' in source
    assert 'reflex_crt::quick_exit(static_cast<uint32_t>(arg(c, 0)))' in source
    imports = (
        '{"MSVCR90.dll", "_exit", ARGC_CDECL, crt_quick_exit}',
        '{"steam_api.dll", "SteamAPI_RunCallbacks", ARGC_CDECL, reflex_steam_run_callbacks}',
        '{"steam_api.dll", "SteamAPI_Shutdown", ARGC_CDECL, reflex_steam_shutdown}',
    )
    for text in imports:
        assert source.count(text) == 1, f"Missing or duplicate ABI binding: {text}"


def test_staging_includes_termination_header():
    patch = (ROOT / "tools" / "patch_reflex_runtime.py").read_text()
    assert '"reflex_crt_termination.h"' in patch
