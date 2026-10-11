"""Asset-free tests for guest-loading-stage instrumentation.

Real translated game units are private; use a minimal fake chunk with the
same generated-function/comment shape to validate fail-closed/idempotence.
"""
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "patch_reflex_cached_loading_stages.py"
spec = importlib.util.spec_from_file_location("loading_stage_patch", SCRIPT)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def make_chunk(dir: Path, missing: str | None = None) -> Path:
    dir.mkdir(parents=True)
    output = dir / "chunk_07.c"
    addresses = [x for x in patch.STAGES if x != missing]
    body = (
        "#include <stdint.h>\n"
        "void fn_0075ed60(X86 *c) {\n"
        + "".join(f"    stub_instruction(); /* {site} CALL */\n" for site in addresses)
        + "}\n"
    )
    output.write_text(body)
    return output


def test_stage_probe_exact_locations_no_guest_mutation(tmp_path):
    generated = tmp_path / "gen"
    chunk = make_chunk(generated)
    original = chunk.read_text()
    output = patch.patch_loading_stages(generated)
    assert output == chunk
    result = chunk.read_text()
    assert result.count(patch.MARKER) == len(patch.STAGES)
    assert result.count("[reflex-load-stage]") == len(patch.STAGES)
    assert result.count("stub_instruction();") == len(patch.STAGES)
    for site in patch.STAGES:
        assert f"pc={site}" in result
    assert "status_event=%08x" in result
    assert "worker_event=%08x" in result
    assert "ebx + 0x161f4u" in result
    assert "ebx + 0x161f8u" in result
    assert patch.patch_loading_stages(generated) == chunk
    assert chunk.read_text() == result
    assert original != result


def test_stage_probe_missing_address_fails_closed(tmp_path):
    generated = tmp_path / "gen"
    chunk = make_chunk(generated, missing="0075ef33")
    original = chunk.read_text()
    with pytest.raises(RuntimeError, match="Expected exactly"):
        patch.patch_loading_stages(generated)
    assert chunk.read_text() == original


def test_stage_probe_multiple_matching_chunks_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    chunk = make_chunk(gen)
    (gen / "chunk_08.c").write_text(chunk.read_text())
    with pytest.raises(RuntimeError, match="Expected one"):
        patch.patch_loading_stages(gen)


def test_stage_probe_marker_tamper_fails_closed(tmp_path):
    gen = tmp_path / "gen"
    chunk = make_chunk(gen)
    patch.patch_loading_stages(gen)
    chunk.write_text(chunk.read_text().replace("[reflex-load-stage]", "[tampered]", 1))
    with pytest.raises(RuntimeError, match="Incomplete"):
        patch.patch_loading_stages(gen)


def test_selected_instructions_from_original_disassembly():
    # Original worker entry is 00760400 -> call 0075ed60; this last site is
    # the actual IAT call to KERNEL32!SetEvent, not a synthetic signal.
    assert patch.STAGES[0] == "0075ed6f"
    assert patch.STAGES[-1] == "0075f293"
