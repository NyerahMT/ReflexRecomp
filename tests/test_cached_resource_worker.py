"""Reflex resource worker queue instrumentation regression tests."""
from pathlib import Path
import importlib.util
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "resource_worker", ROOT / "tools" / "patch_reflex_cached_resource_worker.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def make_chunks(directory: Path, missing=(), repeated=()):
    directory.mkdir(parents=True, exist_ok=True)
    for index, sites in enumerate((probe.WORKER, probe.WRITERS)):
        pcs = [site for site in sites if site not in missing]
        pcs += [site for site in repeated if site in sites]
        (directory / f"chunk_{index:02d}.c").write_text(
            "void synthetic(X86 *c) {\n"
            + "".join(f"  synthetic_instruction(); /* {pc} JE foo */\n" for pc in pcs)
            + "}\n"
        )


def test_worker_checkpoint_probe_is_read_only_and_idempotent(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen)
    results = probe.patch_worker(gen)
    assert len(results) == 2
    for path in results:
        s = path.read_text()
        assert s.count(probe.MARKER) == s.count("[reflex-resource-worker]")
        assert s.count("synthetic_instruction();") >= 2
    assert probe.patch_worker(gen) == results
    assert "rd32(manager + 0xecu)" in results[0].read_text()
    assert "rd32(manager + 0xf0u)" in results[0].read_text()
    assert "rd32((uint32_t)record)" in results[0].read_text()


def test_missing_required_worker_site_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen, missing=("0084c823",))
    before = (gen / "chunk_00.c").read_text()
    with pytest.raises(RuntimeError, match="Expected unique worker checkpoints"):
        probe.patch_worker(gen)
    assert (gen / "chunk_00.c").read_text() == before


def test_duplicate_site_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen, repeated=("0084c7f6",))
    with pytest.raises(RuntimeError, match="Expected unique worker checkpoints"):
        probe.patch_worker(gen)


def test_partial_prior_patch_rejected(tmp_path):
    gen = tmp_path / "gen"
    make_chunks(gen)
    probe.patch_worker(gen)
    path = gen / "chunk_00.c"
    path.write_text(path.read_text().replace("[reflex-resource-worker]", "tamper", 1))
    with pytest.raises(RuntimeError, match="Incomplete previous"):
        probe.patch_worker(gen)


def test_empty_generated_translation_is_error(tmp_path):
    with pytest.raises(RuntimeError, match="No cached translation chunks"):
        probe.patch_worker(tmp_path)


def test_worker_opcode_stage_names():
    assert "0084c823" in probe.WORKER
    assert "0084ca40" in probe.WORKER
    assert "0084bfb8" in probe.WRITERS


def test_generated_instrumentation_compiles_as_c11(tmp_path):
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("C compiler not installed")
    gen = tmp_path / "gen"
    make_chunks(gen)
    probe.patch_worker(gen)
    header = """#include <stdint.h>
#define GUEST_SIZE (0x10000000u)
typedef struct X86 { uint32_t r[8]; } X86;
#define rd32(offset) (offset)
static void synthetic_instruction(void) {}
"""
    for i, chunk_path in enumerate(sorted(gen.glob("chunk_*.c"))):
        source = tmp_path / f"compile_worker_{i}.c"
        source.write_text(header + chunk_path.read_text())
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-fsyntax-only", str(source)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
