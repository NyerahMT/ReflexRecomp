from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "audit_translation_traps.py"
SPEC = importlib.util.spec_from_file_location("translation_trap_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def test_unsupported_opcode_audit_groups_mnemonics(tmp_path):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "chunk_0000.c").write_text(
        "recomp_unmodelled(c, 0x007b3450u); return;\n"
        "recomp_unmodelled(c, 0x007b34d4u); return;\n")
    (gen / "chunk_0001.c").write_text(
        "recomp_unmodelled(c, 0x00784eecu); return;\n")
    asm = tmp_path / "asm"
    asm.mkdir()
    (asm / "007b3400.asm").write_text(
        "007B3450  MULPS XMM0,XMM1\n"
        "007B34D4  MULPS XMM1,XMM0\n")
    (asm / "00784e00.asm").write_text(
        "00784EEC  CVTPS2PD XMM0,XMM0\n")
    found = audit.collect_traps(gen)
    assert len(found) == 3
    opcodes = audit.collect_mnemonics(asm, set(found))
    report = audit.render_audit(found, opcodes)
    assert "Unmodelled guest instruction sites: 3" in report
    assert "Resolved guest mnemonics: 3" in report
    assert "2  MULPS" in report
    assert "1  CVTPS2PD" in report
    assert "007b34d4" in report


def test_empty_generated_dir_fails_closed(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="No generated translation chunks"):
        audit.collect_traps(tmp_path)
