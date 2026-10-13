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
        '  recomp_unmodelled(c,0x004012d0u);return;\n'
        '  recomp_unmodelled(c,0x004012e0u);return;\n'
        '  recomp_unmodelled(c,0x004012f0u);return;\n'
        '  recomp_unmodelled(c,0x00401300u);return;\n'
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
        '004012D0  CVTPS2PD XMM0,XMM1\n'
        '004012E0  CVTPD2PS XMM0,XMM1\n'
        '004012F0  SQRTPS XMM3,XMM0\n'
        '00401300  CMPNEQPS XMM0,XMM1\n'
    )
    counts = mod.patch_cache(gen, asm)
    assert sum(counts.values()) == 9
    for name in ("ADDPS", "MULPS", "SUBPS", "CVTPS2PD", "CVTPD2PS",
                 "SQRTPS", "CMPNEQPS", "CMPEQPS", "DIVPS"):
        assert counts[name] == 1
    rewritten = (gen / "chunk_000.c").read_text()
    assert rewritten.count(mod.INCLUDE) == 1
    assert 'reflex_packed_sse(c, 0x00401254u);' in rewritten
    assert 'reflex_packed_sse(c, 0x0040127eu);' in rewritten
    assert 'reflex_packed_sse(c, 0x004012a0u);' in rewritten
    assert 'reflex_packed_sse(c, 0x00401294u);' in rewritten
    assert 'reflex_packed_sse(c, 0x004012bfu);' in (
        gen / "chunk_001.c").read_text()
    assert all(v == 0 for v in mod.patch_cache(gen, asm).values())
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


def test_bulk_patch_covers_three_reciprocal_families(tmp_path):
    gen = tmp_path / "gen"
    asm = tmp_path / "asm"
    gen.mkdir()
    asm.mkdir()
    source = (
        "void test(X86 *c) {\n"
        " recomp_unmodelled(c,0x00450000u); return;\n"
        " recomp_unmodelled(c,0x00450004u); return;\n"
        " recomp_unmodelled(c,0x00450008u); return;\n"
        " recomp_unmodelled(c,0x0045000cu); return;\n"
        "}\n"
    )
    (gen / "chunk_000.c").write_text(source)
    (asm / "00450000.asm").write_text(
        "00450000  RCPPS XMM0,XMM1\n"
        "00450004  RSQRTPS XMM2,XMM3\n"
        "00450008  RCPSS XMM1,dword ptr [ESP+4]\n"
        "0045000C  CVTPI2PS XMM0,MM0\n"
    )
    counts = mod.patch_cache(gen, asm)
    assert {name: counts[name] for name in ("RCPPS", "RSQRTPS", "RCPSS")} == {
        "RCPPS": 1, "RSQRTPS": 1, "RCPSS": 1
    }
    text = (gen / "chunk_000.c").read_text()
    assert text.count("reflex_packed_sse(c, ") == 3
    assert "recomp_unmodelled(c,0x0045000cu)" in text
    assert all(count == 0 for count in mod.patch_cache(gen, asm).values())


def test_bulk_patch_covers_six_half_register_shuffles(tmp_path):
    gen = tmp_path / "gen"
    asm = tmp_path / "asm"
    gen.mkdir()
    asm.mkdir()
    addresses = [0x00860f2b, 0x00860f2e, 0x00860f5b,
                 0x00860f93, 0x00860f99, 0x00860fbd]
    mnemonics = ["MOVLHPS", "MOVHLPS", "MOVLHPS",
                 "MOVLHPS", "MOVHLPS", "MOVLHPS"]
    (gen / "chunk_086.c").write_text(
        "void test(X86 *c) {\n"
        + "".join(f"recomp_unmodelled(c,0x{addr:08x}u);return;\n" for addr in addresses)
        + "}\n"
    )
    (asm / "00860f00.asm").write_text("".join(
        f"{addr:08X}  {mnemonic} XMM0,XMM1\n"
        for addr, mnemonic in zip(addresses, mnemonics)
    ))
    counts = mod.patch_cache(gen, asm)
    assert counts["MOVLHPS"] == 4
    assert counts["MOVHLPS"] == 2
    rewritten = (gen / "chunk_086.c").read_text()
    assert rewritten.count("reflex_packed_sse(c, ") == 6
    assert all(n == 0 for n in mod.patch_cache(gen, asm).values())
