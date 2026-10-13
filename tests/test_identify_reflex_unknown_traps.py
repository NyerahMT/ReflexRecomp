"""Unit tests for bounded original Reflex unknown-instruction audit."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reflex_unknown_traps", ROOT / "tools" / "identify_reflex_unknown_traps.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


FIXTURE = """Reflex cached-translation unsupported-instruction inventory
Unmodelled guest instruction sites: 3
Resolved guest mnemonics: 1

Sites (address | mnemonic | generated chunk)
0052b547  <not-mapped>     chunk_016.c
0052b550  <not-mapped>     chunk_016.c
00860f2b  MOVLHPS          chunk_086.c
"""


def test_collects_only_unknown_instruction_pcs():
    assert audit.missing_sites(FIXTURE) == [0x0052B547, 0x0052B550]
    with pytest.raises(ValueError, match="missing site table"):
        audit.missing_sites("Unmodelled guest instruction sites: 2")


def test_exact_pc_objdump_and_fail_closed(monkeypatch, tmp_path):
    exe = tmp_path / "verified.exe"
    exe.write_bytes(b"private")
    trap = tmp_path / "trap.txt"
    trap.write_text(FIXTURE)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        pc = int(next(item.split("=")[1] for item in cmd
                      if item.startswith("--start-address=")), 16)
        if pc == 0x0052B547:
            output = " 52b546: 90 nop\n 52b547: 0f 66 c0 pcmpgtd xmm0,xmm0\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")
        return subprocess.CompletedProcess(cmd, 0,
                                           stdout=" 52b550: 0f (bad)\n", stderr="")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    report = audit.audit(trap, exe)
    assert "Audited unmapped sites: 2" in report
    assert "Newly identified by exact-PC objdump: 1" in report
    assert "Still unresolved: 1" in report
    assert "0052b547  PCMPGTD" in report
    assert "0052b550  <unresolved>" in report
    assert len(calls) == 2
    assert all("--stop-address=" in " ".join(c) for c in calls)
    assert "private" not in report


def test_never_claims_success_for_missing_input_or_objdump_errors(monkeypatch, tmp_path):
    exe = tmp_path / "verified.exe"
    exe.write_bytes(b"binary")
    trap = tmp_path / "trap.txt"
    trap.write_text(FIXTURE)
    monkeypatch.setattr(
        audit.subprocess, "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")
    )
    assert "Newly identified by exact-PC objdump: 0" in audit.audit(trap, exe)
    exe.unlink()
    with pytest.raises(FileNotFoundError):
        audit.audit(trap, exe)
