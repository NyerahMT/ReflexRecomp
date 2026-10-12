"""Asset-free tests for verified callback branch target and bounded tracing."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "type1_branch", ROOT / "tools" / "patch_reflex_cached_type1_branch.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
TARGET = 0x0084AE33


def make_chunks(directory, missing="", duplicate=""):
    directory.mkdir()
    for i, group in enumerate(
        (("0084ad8e", "0084ad94"), ("0084ae33",))
    ):
        pcs = [pc for pc in group if pc != missing]
        if duplicate in group:
            pcs.append(duplicate)
        (directory / f"chunk_{i}.c").write_text(
            '#include <stdint.h>\n'
            'typedef struct { uint32_t r[8]; } X86;\n'
            '#define GUEST_SIZE 0x10000000u\n'
            'static uint32_t rd32(uint32_t p) { return p; }\n'
            '__thread unsigned int reflex_type1_callback_trace_enabled = 0u;\n'
            'static void f(X86 *c) {\n' +
            ''.join(f'    (void)c; /* {pc} JNE */\n' for pc in pcs) +
            '}\n'
        )


def test_resolve_exact_original_jne(monkeypatch, tmp_path):
    exe = tmp_path / "MXReflex.exe"
    exe.write_bytes(b"MZ")
    class Result:
        stdout = ("0084ad8d: 90 nop\n"
                  "0084ad8e: 0f 85 9f 00 00 00 jne 84ae33 <callback+0x123>\n")
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: Result())
    assert probe.target_from_private_exe(exe) == TARGET


def test_branch_target_requires_real_jne(monkeypatch, tmp_path):
    exe = tmp_path / "MXReflex.exe"
    exe.write_bytes(b"MZ")
    class Result:
        stdout = "0084ad8e: 90 nop\n"
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(RuntimeError, match="Unexpected"):
        probe.target_from_private_exe(exe)


def test_patches_once_and_does_not_change_guest(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    files, pcs = probe.patch_branch(d, TARGET)
    assert len(files) == 2
    assert pcs == ("0084ad8e", "0084ad94", "0084ae33")
    for path in files:
        s = path.read_text()
        assert s.count(probe.MARKER + " at ") == s.count("[reflex-callback-branch]")
        assert 'arg2=%08x esp=%08x' in s
    original = [f.read_text() for f in files]
    assert probe.patch_branch(d, TARGET) == (files, pcs)
    assert [f.read_text() for f in files] == original


@pytest.mark.parametrize("missing", ["0084ad8e", "0084ad94", "0084ae33"])
def test_missing_pc_atomic(tmp_path, missing):
    d = tmp_path / "gen"
    make_chunks(d, missing)
    orig = [p.read_text() for p in sorted(d.glob("chunk_*.c"))]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_branch(d, TARGET)
    assert [p.read_text() for p in sorted(d.glob("chunk_*.c"))] == orig


def test_duplicate_pc_rejected(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d, duplicate="0084ad94")
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_branch(d, TARGET)


@pytest.mark.skipif(not shutil.which("cc"), reason="C compiler unavailable")
def test_generated_C_syntax(tmp_path):
    d = tmp_path / "gen"
    make_chunks(d)
    files, _ = probe.patch_branch(d, TARGET)
    for file in files:
        subprocess.run(["cc", "-std=c11", "-fsyntax-only", str(file)],
                       check=True, capture_output=True, text=True)
