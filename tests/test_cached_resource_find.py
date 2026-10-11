"""Validate resource-map find tracing is strict C11, idempotent and fail-closed."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_resource_find.py"
spec = importlib.util.spec_from_file_location("resource_find_patch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; } X86;\n'
        '#define GUEST_SIZE 0x20000000u\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0u; }\n'
        'void fn_00544220(X86 *c) {\n'
        '    if (c->r[7] == c->r[3]) return;  /* 0054425b JZ 0x00544290 */\n'
        '}\n'
    )


def test_find_trace_is_idempotent_and_compiles(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    chunk = root / "chunk_048.c"
    chunk.write_text(fixture())

    assert mod.patch_find(root) == chunk
    source = chunk.read_text()
    assert source.count(mod.MARKER) == 1
    assert source.count("[reflex-resource-find]") == 1
    assert "candidate_is_end=%u" in source
    assert "key_words=%08x,%08x,%08x,%08x" in source

    assert mod.patch_find(root) == chunk
    assert chunk.read_text() == source

    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not cc:
        pytest.skip("No C compiler installed")
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-fsyntax-only", str(chunk)],
        check=True, capture_output=True, text=True,
    )


def test_find_trace_fails_closed(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_find(root)

    chunk = root / "chunk_048.c"
    chunk.write_text(fixture().replace("0054425b", "0054425c"))
    with pytest.raises(RuntimeError, match="Expected one 0054425B"):
        mod.patch_find(root)

    chunk.write_text(fixture())
    (root / "chunk_049.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one 00544220"):
        mod.patch_find(root)
