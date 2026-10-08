"""Verify the cached SIMD patcher selects only proven packed arithmetic."""
import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "patch_reflex_cached_simd.py"
SPEC = importlib.util.spec_from_file_location("patch_reflex_cached_simd", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_bulk_patch_preserves_unknown_instruction_and_is_idempotent(tmp_path):
    gen = tmp_path / "gen"
    asm = tmp_path / "asm"
    gen.mkdir()
    asm.mkdir()
    (gen / "chunk_000.c").write_text(
        '#include "x86.h"\n'
        'void demo(X86 *c) {\n'
        '  recomp_unmodelled(c,0x00401254u);return;\n'
        '  recomp_unmodelled(c,0x0040127eu);return;\n'
        '  recomp_unmodelled(c,0x00401294u);return;\n'
        '  recomp_unmodelled(c,0x004012a0u);return;\n'
        '}\n'
    )
    (gen / "chunk_001.c").write_text(
        'void demo2(X86 *c) {\n'
        '  recomp_unmodelled(c,0x004012bfu);return;\n'
        '}\n'
    )
    (asm / "00401000.asm").write_text(
        '00401254  MULPS XMM0,XMM1\n'
        '0040127E  ADDPS XMM2,dword ptr [ESP + 0x10]\n'
        '00401294  DIVPS XMM0,XMM1\n'
        '004012A0  SUBPS XMM3,XMM0\n'
        '004012BF  CMPEQPS XMM0,XMM1\n'
    )
    counts = mod.patch_cache(gen, asm)
    assert counts == {"ADDPS": 1, "MULPS": 1, "SUBPS": 1}
    rewritten = (gen / "chunk_000.c").read_text()
    assert rewritten.count(mod.INCLUDE) == 1
    assert 'reflex_packed_sse(c, 0x00401254u);' in rewritten
    assert 'reflex_packed_sse(c, 0x0040127eu);' in rewritten
    assert 'reflex_packed_sse(c, 0x004012a0u);' in rewritten
    assert 'recomp_unmodelled(c,0x00401294u);return;' in rewritten
    assert 'recomp_unmodelled(c,0x004012bfu);return;' in (
        gen / "chunk_001.c").read_text()
    assert mod.patch_cache(gen, asm) == {"ADDPS": 0, "MULPS": 0, "SUBPS": 0}
    assert (gen / "chunk_000.c").read_text() == rewritten


def test_fail_closed_when_disassembly_is_missing(tmp_path):
    gen = tmp_path / "gen"
    asm = tmp_path / "asm"
    gen.mkdir()
    asm.mkdir()
    (gen / "chunk_000.c").write_text(
        "recomp_unmodelled(c,0x00401254u);return;\n")
    import pytest
    with pytest.raises(RuntimeError, match="disassembly missing"):
        mod.patch_cache(gen, asm)
