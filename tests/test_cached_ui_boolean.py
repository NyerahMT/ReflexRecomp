"""Fail-closed and strict-C11 test for UI Boolean wrapper tracing."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_ui_boolean.py"
spec = importlib.util.spec_from_file_location("reflex_ui_boolean", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; uint32_t eip; } X86;\n'
        '#define GUEST_SIZE (0x10000000u)\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n'
        'static void recomp_return(X86 *c) { (void)c; }\n'
        'void fn_0084a840(X86 *c) {\n'
        '    c->eip = rd32(c->r[4]); c->r[4] += 12u; recomp_return(c); return;  /* 0084a857 RET 0x8 */\n'
        '}\n'
    )


def test_boolean_trace_idempotent_and_valid_c11(tmp_path):
    generated = tmp_path / "gen"
    generated.mkdir()
    chunk = generated / "chunk_085.c"
    chunk.write_text(fixture())
    assert mod.patch_boolean(generated) == chunk
    text = chunk.read_text()
    assert text.count(mod.MARKER) == 1
    assert "[reflex-ui-boolean]" in text
    assert r'eax=%08x\n"' in text
    assert mod.patch_boolean(generated) == chunk
    assert chunk.read_text() == text
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("C compiler unavailable")
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-fsyntax-only", str(chunk)],
        check=True, capture_output=True, text=True,
    )


def test_boolean_trace_fails_closed(tmp_path):
    generated = tmp_path / "gen"
    generated.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_boolean(generated)
    chunk = generated / "chunk_085.c"
    chunk.write_text(fixture().replace("0084a857", "0084a856"))
    with pytest.raises(RuntimeError, match="Missing translated"):
        mod.patch_boolean(generated)
    chunk.write_text(fixture())
    (generated / "chunk_086.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_boolean(generated)
