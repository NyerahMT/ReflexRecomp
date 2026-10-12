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
