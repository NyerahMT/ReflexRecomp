"""Asset-free tests for bounded private assembly diagnostics."""
from pathlib import Path
import importlib.util

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "inspect_reflex_loader_asm.py"
spec = importlib.util.spec_from_file_location("loaderasm", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def sample(directory: Path):
    directory.mkdir()
    (directory / "0084bc70.asm").write_text(
        "0084be11  MOV EAX,ECX\n"
        "0084be35  CALL 00810540\n"
        "0084be40  MOV ESI,EAX\n"
        "0084be49  RET\n"
        "0084bf00  RET\n"
    )


def test_bounded_window(tmp_path):
    d = tmp_path / "asm"
    sample(d)
    result = probe.read_window(d)
    assert [row[0] for row in result] == [0x0084BE11, 0x0084BE35, 0x0084BE40, 0x0084BE49]
    rendered = probe.render(result)
    assert "CALL         00810540" in rendered
    assert "0084bf00" not in rendered


def test_missing_pc_fails_closed(tmp_path):
    d = tmp_path / "asm"
    sample(d)
    (d / "0084bc70.asm").write_text("0084be35  CALL 00810540\n")
    with pytest.raises(RuntimeError, match="Missing required"):
        probe.read_window(d)


def test_duplicate_fails_closed(tmp_path):
    d = tmp_path / "asm"
    sample(d)
    (d / "dup.asm").write_text("0084be35  CALL 00810540\n")
    with pytest.raises(RuntimeError, match="Duplicate guest PC"):
        probe.read_window(d)


def test_rejects_unbounded_window(tmp_path):
    with pytest.raises(ValueError, match="at most"):
        probe.read_window(tmp_path, 0x0084BE11, 0x0084CFFF)


def test_missing_directory(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        probe.read_window(tmp_path / "missing")


def test_objdump_private_pe_disassembly(monkeypatch, tmp_path):
    binary = tmp_path / "MXReflex.exe"
    binary.write_bytes(b"MZ")
    class Result:
        stdout = ("0084be11: 83 ec 04  sub esp,0x4\n"
                  "0084be35: ff 15 34 63 91 00  call DWORD PTR ds:0x916334\n"
                  "0084be40: 8b 44 24 04  mov eax,DWORD PTR [esp+0x4]\n"
                  "0084be49: c3  ret\n")
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "objdump"
        assert cmd[-1] == str(binary)
        return Result()
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    rows = probe.read_pe_window(binary)
    assert [x[0] for x in rows] == [0x0084be11, 0x0084be35, 0x0084be40, 0x0084be49]
    assert rows[1][1] == "call"
    assert rows[1][2] == "DWORD PTR ds:0x916334"


def test_generated_jump_statement_bounded(tmp_path):
    d = tmp_path / "gen"
    d.mkdir()
    (d / "chunk_001.c").write_text(
        "return; /* 0084be35 JMP */\n"
        "NEXT(); /* 0084be40 MOV */\n"
        "secret_content_from_other_PC(); /* 0084be46 MOV */\n")
    text = "\n".join(probe.inspect_generated_jump(d))
    assert "0084be35 chunk_001.c: return;" in text
    assert "0084be40 chunk_001.c: NEXT();" in text
    assert "secret_content" not in text


def test_generated_jump_duplicate_fails(tmp_path):
    d = tmp_path / "gen"
    d.mkdir()
    (d / "chunk_000.c").write_text("x(); /* 0084be35 JMP */\n")
    (d / "chunk_001.c").write_text("y(); /* 0084be35 JMP */\n"
                                    "z(); /* 0084be40 MOV */\n")
    with pytest.raises(RuntimeError, match="Missing/duplicate"):
        probe.inspect_generated_jump(d)


def test_callback_quoted_guest_sites(tmp_path):
    d = tmp_path / "gen"
    d.mkdir()
    (d / "chunk_085.c").write_text(
        "CALL(c, 0x84ad10u); /* 0084beef CALL */\n"
        "c->r[0] = 1; /* 0084bf12 MOV */\n"
        "secret(); /* 0084bf16 NOP */\n"
    )
    result = probe.inspect_generated_jump(d, ("0084beef", "0084bf12"))
    assert "0084beef chunk_085.c: CALL(c, 0x84ad10u);" in "\n".join(result)
    assert "0084bf12 chunk_085.c: c->r[0] = 1;" in "\n".join(result)
    assert "secret()" not in "\n".join(result)


def test_invalid_sites_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="distinct"):
        probe.inspect_generated_jump(tmp_path, ("0084beef", "0084beef"))
    with pytest.raises(ValueError, match="lowercase"):
        probe.inspect_generated_jump(tmp_path, ("0084BEEF",))
