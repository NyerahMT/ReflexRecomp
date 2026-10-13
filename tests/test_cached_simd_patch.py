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
    assert counts["CVTPI2PS"] == 1
    assert text.count("reflex_packed_sse(c, ") == 4
    assert "reflex_packed_sse(c, 0x0045000cu);" in text
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

def test_bulk_patch_selects_six_sse2_integer_conversion_sites(tmp_path):
    gen = tmp_path / "gen"
    asm = tmp_path / "asm"
    gen.mkdir()
    asm.mkdir()
    addresses = [0x0042c262, 0x0042c266, 0x0042c26a,
                 0x0042c3bb, 0x0042c3bf, 0x0042c3c3]
    names = ["PCMPGTD", "CVTPS2DQ", "CVTDQ2PS"] * 2
    (gen / "chunk_005.c").write_text(
        "void test(X86 *c) {\n"
        + "".join(f"recomp_unmodelled(c,0x{pc:08x}u);return;\n" for pc in addresses)
        + "}\n"
    )
    (asm / "0042c000.asm").write_text("".join(
        f"{pc:08X}  {name} XMM0,XMM1\n"
        for pc, name in zip(addresses, names)
    ))
    count = mod.patch_cache(gen, asm)
    assert {name: count[name] for name in set(names)} == {
        "PCMPGTD": 2, "CVTPS2DQ": 2, "CVTDQ2PS": 2
    }
    assert (gen / "chunk_005.c").read_text().count("reflex_packed_sse(c,") == 6
    assert all(x == 0 for x in mod.patch_cache(gen, asm).values())


def test_last_19_patches_with_exact_pe_lookup(tmp_path, monkeypatch):
    """17 absent Ghidra PCs plus two explicitly listed MMX CVTPI2PS sites."""
    from pathlib import Path
    import subprocess

    gen = tmp_path / "gen"
    listing = tmp_path / "asm"
    gen.mkdir()
    listing.mkdir()
    exe = tmp_path / "verified-private.exe"
    exe.write_bytes(b"fixture, not the original game")

    pd = [0x0052B547, 0x0052B550, 0x0052B56C, 0x0052B5A9,
          0x0052B5E6, 0x0052B5F2, 0x00533629, 0x0053557C,
          0x00565429, 0x006305FE, 0x0063075A]
    ps = [0x00630682, 0x006306C2, 0x006306E6,
          0x00630702, 0x00630712, 0x00630761]
    mm = [0x0041C59B, 0x0041C5A3]
    addresses = sorted(pd + ps + mm)
    (listing / "known.asm").write_text("".join(
        f"{pc:08X}  CVTPI2PS XMM0,MM1\n" for pc in mm
    ))
    (gen / "chunk_000.c").write_text(
        "void sample(X86 *c) {\n" +
        "".join(f"  recomp_unmodelled(c,0x{pc:08x}u);return;\n" for pc in addresses) +
        "}\n"
    )

    def fake_objdump(command, **kwargs):
        pc = int(next(x.rsplit("=", 1)[1] for x in command
                      if x.startswith("--start-address=")), 16)
        if pc in pd:
            instr, name = "0f 5a c1", "cvtps2pd"
        elif pc in ps:
            instr, name = "66 0f 5a c1", "cvtpd2ps"
        else:
            raise AssertionError("Known Ghidra CVTPI2PS should not be probed")
        return subprocess.CompletedProcess(
            command, 0,
            stdout=f" {pc:08x}: {instr} {name} xmm0,xmm1\n", stderr=""
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_objdump)
    counts = mod.patch_cache(gen, listing, exe=exe, expect_remaining=0)
    assert counts["CVTPS2PD"] == 11
    assert counts["CVTPD2PS"] == 6
    assert counts["CVTPI2PS"] == 2
    assert sum(counts.values()) == 19
    assert (gen / "chunk_000.c").read_text().count("reflex_packed_sse(c,") == 19
    assert all(x == 0 for x in mod.patch_cache(gen, listing).values())


def test_exact_pe_fallback_refuses_wrong_opcode_and_mnemonic(tmp_path, monkeypatch):
    import subprocess
    exe = tmp_path / "private.exe"
    exe.write_bytes(b"fixture")

    def fake_objdump(command, **kwargs):
        start = int(next(x.rsplit("=", 1)[1] for x in command
                         if x.startswith("--start-address=")), 16)
        instr, name = ("66 0f 5a c1", "cvtps2pd") if start == 0x10000 else (
            "0f 5a c1", "cvtpd2ps"
        )
        return subprocess.CompletedProcess(
            command, 0,
            stdout=f" {start:08x}: {instr} {name} xmm0,xmm1\n",
            stderr=""
        )
    monkeypatch.setattr(mod.subprocess, "run", fake_objdump)
    assert mod.inspect_unknown_pe(exe, {0x10000, 0x10010}) == {}
