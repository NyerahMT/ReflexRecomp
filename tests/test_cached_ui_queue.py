"""Test safe, idempotent direct-call queue instrumentation and C11 syntax."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "patch_reflex_cached_ui_queue.py"
SPEC = importlib.util.spec_from_file_location("reflex_ui_direct_queue", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def fixture_code():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; } X86;\n'
        '#define GUEST_SIZE (0x20000000u)\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n'
        'static void body_0084c190(X86 *c, uint32_t entry_) {\n'
        '    (void)c; (void)entry_;\n'
        '}\n'
        'void fn_0084c190(X86 *c) { body_0084c190(c, 0u); }\n'
    )


def test_direct_call_queue_tracing_idempotent_and_valid_c(tmp_path):
    generated = tmp_path / "gen"
    generated.mkdir()
    (generated / "chunk_085.c").write_text(fixture_code())
    target = mod.patch_queue(generated)
    assert target.name == "chunk_085.c"
    changed = target.read_text()
    assert mod.MARKER in changed
    assert changed.count(mod.MARKER) == 1
    assert 'entry_ == 0u' in changed
    assert 'manager <= GUEST_SIZE - 0xfcu' in changed
    assert '[reflex-direct-queue]' in changed
    assert 'gm_valid(' not in changed
    assert mod.patch_queue(generated) == target
    assert target.read_text() == changed

    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("C compiler not installed")
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-fsyntax-only", str(target)],
        check=True, capture_output=True, text=True,
    )


def test_direct_call_queue_missing_and_duplicate_fail_closed(tmp_path):
    generated = tmp_path / "gen"
    generated.mkdir()
    with pytest.raises(RuntimeError, match="No cached translation chunks"):
        mod.patch_queue(generated)
    (generated / "chunk_085.c").write_text("void fn_dummy(void) {}\n")
    with pytest.raises(RuntimeError, match="Expected one queue translation"):
        mod.patch_queue(generated)
    (generated / "chunk_085.c").write_text(fixture_code())
    (generated / "chunk_086.c").write_text(fixture_code())
    with pytest.raises(RuntimeError, match="Expected one queue translation"):
        mod.patch_queue(generated)
