"""Verify resource resolver trace injection is strict C11 and idempotent."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_ui_lookup.py"
spec = importlib.util.spec_from_file_location("ui_lookup_patch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        'typedef struct X86 { uint32_t r[8]; uint32_t eip; } X86;\n'
        '#define GUEST_SIZE (0x10000000u)\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n'
        'static void recomp_return(X86 *c) { (void)c; }\n'
        'void fn_0084a890(X86 *c) {\n'
        '    if (!c->r[0]) {\n'
        '        c->eip = rd32(c->r[4]); c->r[4] += 12u; recomp_return(c); return;  /* 0084a90d RET 0x8 */\n'
        '    }\n'
        '    c->eip = rd32(c->r[4]); c->r[4] += 12u; recomp_return(c); return;  /* 0084a921 RET 0x8 */\n'
        '}\n'
    )


def test_trace_is_idempotent_and_c11(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    chunk = gen / "chunk_085.c"
    chunk.write_text(fixture())
    assert mod.patch_lookup(gen) == chunk
    saved = chunk.read_text()
    assert saved.count(mod.MARKER) == 2
    # Generated C must emit a real log line ending, not literal backslash-n.
    assert r'result=%08x\n"' in saved
    assert r'result=%08x\\n"' not in saved
    assert mod.patch_lookup(gen) == chunk
    assert chunk.read_text() == saved
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc:
        subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-fsyntax-only", str(chunk)], check=True,
                       capture_output=True, text=True)


def test_trace_fails_if_missing_or_duplicate(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_lookup(gen)
    a = gen / "chunk_085.c"
    a.write_text(fixture().replace("0084a921", "0084a922"))
    with pytest.raises(RuntimeError, match="Missing translated"):
        mod.patch_lookup(gen)
    a.write_text(fixture())
    (gen / "chunk_086.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one"):
        mod.patch_lookup(gen)
