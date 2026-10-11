"""Test direct-call UI resource consumer tracing without private game code."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

PATH = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_ui_consumer.py"
spec = importlib.util.spec_from_file_location("ui_consumer", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; } X86;\n'
        '#define GUEST_SIZE (0x20000000u)\n'
        'static uint32_t rd32(uint32_t addr) { (void)addr; return 0; }\n'
        'static void body_005dbe50(X86 *c, uint32_t entry_) {\n'
        '    (void)c; (void)entry_;\n'
        '}\n'
        'void fn_005dbe50(X86 *c) { body_005dbe50(c, 0u); }\n'
    )


def test_trace_compiles_is_safe_and_idempotent(tmp_path):
    folder = tmp_path / "gen"
    folder.mkdir()
    chunk = folder / "chunk_050.c"
    chunk.write_text(fixture())
    assert mod.patch_consumer(folder) == chunk
    output = chunk.read_text()
    assert output.count(mod.MARKER) == 1
    assert r"esi=%08x\n" in output
    assert mod.patch_consumer(folder) == chunk
    assert chunk.read_text() == output
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C compiler unavailable")
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsyntax-only", str(chunk)],
                   check=True, capture_output=True, text=True)


def test_consumer_trace_fails_closed(tmp_path):
    folder = tmp_path / "gen"
    folder.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_consumer(folder)
    chunk = folder / "chunk_050.c"
    chunk.write_text("void unrelated(void) {}\n")
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_consumer(folder)
    chunk.write_text(fixture())
    (folder / "chunk_051.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_consumer(folder)
