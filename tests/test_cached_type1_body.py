"""C11-safe exact body tracing for the blocked MXUI type-1 resource."""
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "patch_reflex_cached_type1_body.py"
spec = importlib.util.spec_from_file_location("type1_body", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def chunks(folder: Path, missing: str = "", duplicated: str = ""):
    folder.mkdir(parents=True, exist_ok=True)
    for idx, group in enumerate([probe.STAGES[:9], probe.STAGES[9:]]):
        selected = [pc for pc in group if pc != missing]
        if duplicated in group:
            selected.append(duplicated)
        file = folder / f"chunk_{idx:02d}.c"
        file.write_text(
            '#include <stdint.h>\n'
            'static void body_0084bc70(X86 *c, uint32_t entry_) {\n' +
            "".join(f"    original_instruction(); /* {pc} CALL */\n"
                    for pc in selected) + "}\n"
        )


def test_original_type1_sites_across_translated_chunks(tmp_path):
    source = tmp_path / "gen"
    chunks(source)
    files = probe.patch_type1_body(source)
    assert len(files) == 2
    for file in files:
        content = file.read_text()
        assert content.count(probe.MARKER) == content.count("[reflex-type1-body]")
        assert "original_instruction();" in content
        assert "rd32(obj + 0x94u)" in content
        assert "count=%u status=%08x" in content
    before = [file.read_text() for file in files]
    assert probe.patch_type1_body(source) == files
    assert before == [file.read_text() for file in files]


def test_missing_required_site_is_atomic(tmp_path):
    source = tmp_path / "missing"
    chunks(source, missing="0084bfb8")
    files = sorted(source.glob("chunk_*.c"))
    old = [f.read_text() for f in files]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1_body(source)
    assert [f.read_text() for f in files] == old


def test_duplicate_stage_fails_closed(tmp_path):
    source = tmp_path / "duplicate"
    chunks(source, duplicated="0084be11")
    files = sorted(source.glob("chunk_*.c"))
    old = [f.read_text() for f in files]
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.patch_type1_body(source)
    assert [f.read_text() for f in files] == old


def test_tampered_probe_fails_closed(tmp_path):
    source = tmp_path / "partial"
    chunks(source)
    files = probe.patch_type1_body(source)
    files[0].write_text(files[0].read_text().replace("[reflex-type1-body]", "tampered", 1))
    with pytest.raises(RuntimeError, match="Partial existing"):
        probe.patch_type1_body(source)


def test_original_x86_pc_boundaries():
    assert probe.STAGES[0] == "0084bcbc"
    assert probe.STAGES[-1] == "0084bfb8"
    assert "0084be40" in probe.STAGES
    assert "0084beed" in probe.STAGES
