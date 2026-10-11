"""Check guest comparator tracing is strict C11, idempotent and fail-closed."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_cached_resource_cmp.py"
spec = importlib.util.spec_from_file_location("cmp_patch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return (
        "#include <stdint.h>\n"
        "typedef struct X86 { uint32_t r[8]; } X86;\n"
        "#define GUEST_SIZE 0x20000000u\n"
        "static uint32_t rd32(uint32_t p) { (void)p; return 0u; }\n"
        "void fn_005449d0(X86 *c) {\n"
        "    if (c->r[0] == 0u) return; /* 00544a18 TEST EAX,EAX */\n"
        "}\n"
    )


def test_comparator_tracing_compiles_and_is_idempotent(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    source_path = root / "chunk_048.c"
    source_path.write_text(fixture())
    assert mod.patch_cmp(root) == source_path
    source = source_path.read_text()
    assert source.count(mod.MARKER) == 1
    assert source.count("[reflex-resource-cmp]") == 1
    assert "cmp=%d" in source
    assert "esp - 8u" in source
    assert mod.patch_cmp(root) == source_path
    assert source_path.read_text() == source
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("No C compiler")
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-fsyntax-only", str(source_path)],
        check=True, capture_output=True, text=True,
    )


def test_comparator_tracing_fails_closed(tmp_path):
    root = tmp_path / "gen"
    root.mkdir()
    with pytest.raises(RuntimeError, match="No cached"):
        mod.patch_cmp(root)
    source_path = root / "chunk_048.c"
    source_path.write_text(fixture().replace("00544a18", "00544a19"))
    with pytest.raises(RuntimeError, match="Expected one 00544A18"):
        mod.patch_cmp(root)
    source_path.write_text(fixture())
    (root / "chunk_049.c").write_text(fixture())
    with pytest.raises(RuntimeError, match="Expected one 005449d0"):
        mod.patch_cmp(root)
