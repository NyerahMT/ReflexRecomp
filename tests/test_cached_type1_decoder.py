"""Unit tests for bounded MXTables nested-decoder guest trace."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mxtables_decoder", ROOT / "tools" / "patch_reflex_cached_type1_decoder.py")
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def fixture(directory, missing="", duplicate=""):
    directory.mkdir()
    groups = (
        ("004eefa0", "004eefa1", "004ef017", "004ef210", "004ef3ff"),
        ("004f019e",),
    )
    for i, group in enumerate(groups):
        pcs = [pc for pc in group if pc != missing]
        if duplicate in group:
            pcs.append(duplicate)
        (directory / f"chunk_{i:03d}.c").write_text(
            "#include <stdint.h>\n"
            "typedef struct { uint32_t r[8]; } X86;\n"
            "#define GUEST_SIZE 0x10000000u\n"
            "static uint32_t rd32(uint32_t p) { return p; }\n"
            "static void f(X86 *c) {\n"
            + "".join(f"    (void)c; /* {pc} MOV */\n" for pc in pcs)
            + "    (void)c; /* 004ef400 RET */\n}\n"
        )


def test_precise_sites_idempotent_and_bounded(tmp_path):
    d = tmp_path / "gen"
    fixture(d)
    paths, pcs = decoder.patch_inner_decoder(d)
    assert len(paths) == 2
    assert {"004eefa0", "004ef3ff", "004f019e"}.issubset(pcs)
    assert "004ef400" not in pcs
    original = [p.read_text() for p in paths]
    for content in original:
        assert content.count(decoder.MARKER + " at ") == content.count(
            "[reflex-mxtables-inner]")
        assert "sp0=%08x sp4=%08x" in content
        assert "at 004ef400" not in content
    assert decoder.patch_inner_decoder(d) == (paths, pcs)
    assert [p.read_text() for p in paths] == original


@pytest.mark.parametrize("missing", ["004eefa0", "004f019e"])
def test_missing_required_pc_is_atomic(tmp_path, missing):
    d = tmp_path / "gen"
    fixture(d, missing=missing)
    before = [p.read_text() for p in sorted(d.glob("chunk_*.c"))]
    with pytest.raises(RuntimeError, match="Missing or duplicate"):
        decoder.patch_inner_decoder(d)
    assert [p.read_text() for p in sorted(d.glob("chunk_*.c"))] == before


def test_duplicate_pc_rejected(tmp_path):
    d = tmp_path / "gen"
    fixture(d, duplicate="004ef017")
    with pytest.raises(RuntimeError, match="Missing or duplicate"):
        decoder.patch_inner_decoder(d)


def test_partial_install_rejected(tmp_path):
    d = tmp_path / "gen"
    fixture(d)
    paths, _ = decoder.patch_inner_decoder(d)
    paths[0].write_text(paths[0].read_text().replace(
        "[reflex-mxtables-inner]", "broken", 1))
    with pytest.raises(RuntimeError, match="Partially installed"):
        decoder.patch_inner_decoder(d)


@pytest.mark.skipif(not shutil.which("cc"), reason="C compiler unavailable")
def test_instrumented_chunks_compile_as_c11(tmp_path):
    d = tmp_path / "gen"
    fixture(d)
    paths, _ = decoder.patch_inner_decoder(d)
    for path in paths:
        subprocess.run(["cc", "-std=c11", "-fsyntax-only", str(path)],
                       check=True, capture_output=True, text=True)
