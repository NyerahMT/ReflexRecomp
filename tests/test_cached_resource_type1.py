"""Guest type-1 resource processing path diagnostics must be safe C11."""
from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "type1_trace", ROOT / "tools" / "patch_reflex_cached_resource_type1.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def make_chunks(directory: Path, missing=(), duplicate=()):
    directory.mkdir(parents=True)
    for i, pcs in enumerate((probe.SITES[:4], probe.SITES[4:])):
        entries = [pc for pc in pcs if pc not in missing]
        entries += [pc for pc in duplicate if pc in pcs]
        (directory / f"chunk_{i:03}.c").write_text(
            "void synthetic(X86 *c) {\n"
            + "".join(f"    fake_guest_op(); /* {pc} CALL */\n" for pc in entries)
            + "}\n"
        )


def test_probe_matches_original_type1_sites_without_logic_edits(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen)
    result = probe.patch_type1(gen)
    assert len(result) == 2
    for path in result:
        text = path.read_text()
        assert text.count(probe.MARKER) == text.count("[reflex-type1-resource]")
        assert text.count("fake_guest_op();") == 4
    assert probe.patch_type1(gen) == result
    assert result[0].read_text().count(probe.MARKER) == 4


def test_missing_required_entry_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen, missing=("0084cad9",))
    original = (gen / "chunk_000.c").read_text()
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1(gen)
    assert (gen / "chunk_000.c").read_text() == original


def test_duplicate_callback_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen, duplicate=("0084cb79",))
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1(gen)


def test_broken_reinstall_is_rejected(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen)
    probe.patch_type1(gen)
    file = gen / "chunk_000.c"
    file.write_text(file.read_text().replace("[reflex-type1-resource]", "tampered", 1))
    with pytest.raises(RuntimeError, match="Partial previously installed"):
        probe.patch_type1(gen)


def test_compile_emitted_diagnostics_as_c11(tmp_path):
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("No C compiler")
    gen = tmp_path / "gen"
    make_chunks(gen)
    probe.patch_type1(gen)
    header = """#include <stdint.h>
#define GUEST_SIZE (0x10000000u)
typedef struct { uint32_t r[8]; } X86;
#define rd32(x) (x)
static void fake_guest_op(void) {}
"""
    for i, f in enumerate(sorted(gen.glob("chunk_*.c"))):
        source = tmp_path / f"type1_{i}.c"
        source.write_text(header + f.read_text())
        p = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-fsyntax-only", str(source)],
            capture_output=True, text=True,
        )
        assert p.returncode == 0, p.stderr


def test_original_addresses_track_before_and_after_processing():
    assert probe.SITES[0] == "0084caa3"
    assert "0084cb79" in probe.SITES
    assert probe.SITES[-1] == "0084cb7e"
