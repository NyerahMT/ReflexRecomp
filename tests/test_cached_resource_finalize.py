"""Validate generated resource finalizer probes remain strict C11 and idempotent."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

PATH = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_resource_finalize.py"
spec = importlib.util.spec_from_file_location("resource_finalizer", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; uint32_t eip; } X86;\n'
        '#define GUEST_SIZE (0x20000000u)\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n'
        'static void recomp_return(X86 *c) { (void)c; }\n'
        'void fn_00543cd0(X86 *c) {\n'
        '    if (c->r[0] == 0) {\n'
        '        c->eip = rd32(c->r[4]); c->r[4] += 8u; recomp_return(c); return;  /* 00543d92 RET 0x4 */\n'
        '    }\n'
        '    c->eip = rd32(c->r[4]); c->r[4] += 8u; recomp_return(c); return;  /* 00543da0 RET 0x4 */\n'
        '}\n'
    )


def test_sparse_finalizer_probe_is_idempotent_and_compiles(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    chunk = root / "chunk_050.c"
    chunk.write_text(fixture())
    assert mod.patch_finalize(root) == chunk
    source = chunk.read_text()
    assert source.count(mod.MARKER) == 2
    assert source.count("[reflex-resource-final]") == 2
    assert r'edi=%08x\n"' in source
    assert mod.patch_finalize(root) == chunk
    assert chunk.read_text() == source
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("No C compiler installed")
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-fsyntax-only", str(chunk)],
        check=True, capture_output=True, text=True,
    )


def test_finalizer_probe_fails_closed(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_finalize(root)
    f = root / "chunk_050.c"
    f.write_text(fixture().replace("00543da0", "00543d9f"))
    with pytest.raises(RuntimeError, match="Missing resource"):
        mod.patch_finalize(root)
    f.write_text(fixture())
    (root / "chunk_051.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_finalize(root)
