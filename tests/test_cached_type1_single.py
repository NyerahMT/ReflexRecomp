"""Tests for the single-entry type-1 loader trace without copyrighted assets."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "single_loader", ROOT / "tools" / "patch_reflex_cached_type1_single.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

PCS = ("0084be40", "0084be5d", "0084beed", "0084bf12",
       "0084bf49", "0084bfb8")


def chunks(directory, missing="", duplicate=""):
    directory.mkdir()
    for i, pcs in enumerate((PCS[:3], PCS[3:])):
        sites = [pc for pc in pcs if pc != missing]
        if duplicate in pcs:
            sites.append(duplicate)
        (directory / f"chunk_{i}.c").write_text(
            '#include <stdint.h>\n'
            'typedef struct { uint32_t r[8]; } X86;\n'
            '#define GUEST_SIZE 0x10000000u\n'
            'static uint32_t rd32(uint32_t p) { return p; }\n'
            'static void guest(X86 *c) {\n'
            + "".join(f'    (void)c; /* {pc} MOV */\n' for pc in sites)
            + '    (void)c; /* 0084bfba RET */\n}\n'
        )


def test_bounded_instrumentation_and_idempotency(tmp_path):
    d = tmp_path / "gen"
    chunks(d)
    files, pcs = probe.patch_single_entry(d)
    assert len(files) == 2
    assert pcs == sorted(PCS)
    for path in files:
        content = path.read_text()
        assert content.count(probe.MARKER) == content.count("[reflex-type1-single]")
        assert "rd32(obj + 0x84u) == 1u" in content
        assert "rd32(obj + 0x90u) == 0u" in content
        assert "/* 0084bfba RET */" in content
        assert "at 0084bfba" not in content
    original = [p.read_text() for p in files]
    assert probe.patch_single_entry(d) == (files, pcs)
    assert original == [p.read_text() for p in files]


@pytest.mark.parametrize("missing", ["0084be40", "0084bfb8"])
def test_missing_anchor_fails_without_writes(tmp_path, missing):
    d = tmp_path / "gen"
    chunks(d, missing=missing)
    before = [p.read_text() for p in sorted(d.glob("chunk_*.c"))]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_single_entry(d)
    assert before == [p.read_text() for p in sorted(d.glob("chunk_*.c"))]


def test_duplicate_anchor_fails(tmp_path):
    d = tmp_path / "gen"
    chunks(d, duplicate="0084bf12")
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_single_entry(d)


def test_partial_probe_is_rejected(tmp_path):
    d = tmp_path / "gen"
    chunks(d)
    files, _ = probe.patch_single_entry(d)
    files[0].write_text(files[0].read_text().replace(
        "[reflex-type1-single]", "broken", 1))
    with pytest.raises(RuntimeError, match="Partial installed"):
        probe.patch_single_entry(d)


@pytest.mark.skipif(not shutil.which("cc"), reason="C compiler unavailable")
def test_generated_chunks_compile_as_c11(tmp_path):
    d = tmp_path / "gen"
    chunks(d)
    files, _ = probe.patch_single_entry(d)
    for path in files:
        subprocess.run(["cc", "-std=c11", "-fsyntax-only", str(path)],
                       capture_output=True, text=True, check=True)
