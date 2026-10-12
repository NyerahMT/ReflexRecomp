"""Tests for no-guest-mutation, callback-scoped generated-C diagnostics."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "callback_probe", ROOT / "tools" / "patch_reflex_cached_type1_callback.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def make_chunks(path, missing="", duplicate=""):
    path.mkdir()
    for index, pcs in enumerate((("0084ad10", "0084ad12", "0084ad1a", "0084ae25", "0084af80", "0084b200", "004f0170", "004f0192"),
                                 ("0084beef", "0084bf12"))):
        selected = [pc for pc in pcs if pc != missing]
        if duplicate in pcs:
            selected.append(duplicate)
        (path / f"chunk_{index}.c").write_text(
            '#include <stdint.h>\n'
            'typedef struct { uint32_t r[8]; } X86;\n'
            '#define GUEST_SIZE 0x10000000u\n'
            'static uint32_t rd32(uint32_t p) { return p; }\n'
            'static void guest(X86 *c) {\n' +
            ''.join(f'    (void)c; /* {pc} MOV */\n' for pc in selected) +
            '}\n'
        )


def test_scoped_probe_install_and_reinstall(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    files, pcs = probe.patch_callback(d)
    assert len(files) == 2
    assert {"0084ad10", "0084ae25", "0084af80", "0084b200", "004f0170", "004f0192", "0084beef", "0084bf12"}.issubset(pcs)
    a, b = [p.read_text() for p in files]
    assert "extern __thread unsigned int" in a
    assert "extern __thread unsigned int" not in b
    assert "rd32(obj + 0x84u) == 1u" in b
    assert "returned pc=0084bf12" in b
    assert "pc=0084ad10" in a
    assert probe.patch_callback(d) == (files, pcs)
    assert [p.read_text() for p in files] == [a, b]


@pytest.mark.parametrize("missing", ["0084ad10", "004f0170", "0084beef", "0084bf12"])
def test_missing_site_fails_without_writes(tmp_path, missing):
    d = tmp_path / "gen"
    make_chunks(d, missing=missing)
    old = [p.read_text() for p in sorted(d.glob("chunk_*.c"))]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_callback(d)
    assert old == [p.read_text() for p in sorted(d.glob("chunk_*.c"))]


def test_duplicate_site_fails(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d, duplicate="0084ad10")
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_callback(d)


@pytest.mark.skipif(not shutil.which("cc"), reason="C compiler unavailable")
def test_generated_chunks_compile(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    files, _ = probe.patch_callback(d)
    for path in files:
        subprocess.run(["cc", "-std=c11", "-fsyntax-only", str(path)],
                       check=True, capture_output=True, text=True)


def test_extended_window_does_not_trace_beyond_b2ff(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    file = d / "chunk_0.c"
    file.write_text(file.read_text().replace(
        "}\n", "    (void)c; /* 0084b300 MOV */\n}\n"))
    files, pcs = probe.patch_callback(d)
    assert "0084ae25" in pcs
    assert "0084b300" not in pcs
    assert "at 0084b300" not in file.read_text()


def test_nested_callee_range_is_bounded(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    file = d / "chunk_0.c"
    file.write_text(file.read_text().replace(
        "}\n", "    (void)c; /* 004f0300 RET */\n}\n"))
    files, pcs = probe.patch_callback(d)
    assert "004f0170" in pcs
    assert "004f0300" not in pcs
    assert "at 004f0300" not in file.read_text()
