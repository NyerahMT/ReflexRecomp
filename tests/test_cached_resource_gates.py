"""Strict-C11, safety, idempotence and fail-closed resource gate tracing."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_resource_gates.py"
spec = importlib.util.spec_from_file_location("reflex_gate_patch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; } X86;\n'
        '#define GUEST_SIZE 0x20000000u\n'
        'static uint32_t rd32(uint32_t ptr) { (void)ptr; return 0u; }\n'
        'void fn_00543cd0(X86 *c) {\n'
        '    if (c->r[0] == 0u) return;  /* 00543d31 JZ 0x00543d8a */\n'
        '    if (c->r[0] == 1u) return;  /* 00543d45 JZ 0x00543d8a */\n'
        '}\n'
    )


def test_gates_compile_and_do_not_mutate_guest_state(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    path = root / "chunk_048.c"
    path.write_text(fixture())
    assert mod.patch_gates(root) == path
    patched = path.read_text()
    assert patched.count(mod.MARKER) == 2
    assert patched.count("[reflex-resource-gate]") == 2
    assert "local == edi" in patched and "esi + 0x24u" in patched
    assert r'eax=%08x\n"' in patched
    assert mod.patch_gates(root) == path
    assert path.read_text() == patched
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not cc:
        pytest.skip("No C compiler installed")
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(path)],
        check=True, capture_output=True, text=True,
    )


def test_gate_instrumentation_fails_closed(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_gates(root)
    chunk = root / "chunk_048.c"
    chunk.write_text(fixture().replace("00543d45", "00543d46"))
    with pytest.raises(RuntimeError, match="Expected early"):
        mod.patch_gates(root)
    chunk.write_text(fixture())
    (root / "chunk_049.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_gates(root)
