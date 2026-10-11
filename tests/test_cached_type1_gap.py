"""Verify fail-closed, idempotent, compile-safe translated-PC gap tracing."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "type1_gap", ROOT / "tools" / "patch_reflex_cached_type1_gap.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
PCS = ("0084be11", "0084be16", "0084be21", "0084be30", "0084be40")


def make_chunks(directory, missing="", duplicate=""):
    directory.mkdir(parents=True, exist_ok=True)
    for i, group in enumerate((PCS[:3], PCS[3:])):
        addresses = [pc for pc in group if pc != missing]
        if duplicate in group:
            addresses.append(duplicate)
        (directory / f"chunk_{i:02d}.c").write_text(
            '#include <stdint.h>\n'
            'typedef struct { uint32_t r[8]; } X86;\n'
            '#define GUEST_SIZE 0x10000000u\n'
            'static uint32_t rd32(uint32_t p) { return p; }\n'
            'static void f(X86 *c) {\n' +
            ''.join(f'    (void)c; /* {pc} MOV */\n' for pc in addresses) +
            '    (void)c; /* 0084be41 MOV */\n}\n'
        )


def test_instruments_only_actual_original_pc_range(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    changed, pcs = probe.patch_type1_gap(d)
    assert len(changed) == 2
    assert pcs == sorted(PCS)
    for path in changed:
        content = path.read_text()
        assert content.count(probe.MARKER) == content.count("[reflex-type1-gap]")
        assert '#include <stdio.h>' in content
        assert 'sp0=%08x sp4=%08x' in content
        assert '/* 0084be41 MOV */' in content
        assert 'at 0084be41' not in content
    original = [p.read_text() for p in changed]
    assert probe.patch_type1_gap(d) == (changed, pcs)
    assert [p.read_text() for p in changed] == original


@pytest.mark.parametrize("missing", ["0084be11", "0084be40"])
def test_missing_anchor_keeps_all_chunks_untouched(tmp_path, missing):
    d = tmp_path / "gen"
    make_chunks(d, missing=missing)
    before = [p.read_text() for p in sorted(d.glob("*.c"))]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1_gap(d)
    assert [p.read_text() for p in sorted(d.glob("*.c"))] == before


def test_duplicate_pc_fails_atomically(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d, duplicate="0084be21")
    before = [p.read_text() for p in sorted(d.glob("*.c"))]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1_gap(d)
    assert [p.read_text() for p in sorted(d.glob("*.c"))] == before


def test_partial_probe_fails_closed(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    paths, _ = probe.patch_type1_gap(d)
    paths[0].write_text(paths[0].read_text().replace("[reflex-type1-gap]", "changed", 1))
    with pytest.raises(RuntimeError, match="Partial existing"):
        probe.patch_type1_gap(d)


@pytest.mark.skipif(not shutil.which("cc"), reason="C compiler unavailable")
def test_generated_c_compiles_with_c11(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    paths, _ = probe.patch_type1_gap(d)
    for path in paths:
        subprocess.run(["cc", "-std=c11", "-fsyntax-only", str(path)],
                       check=True, capture_output=True, text=True)
