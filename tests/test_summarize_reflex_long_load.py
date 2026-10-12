"""Tests ensuring a long-running guest is never confused with completed loading."""
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location(
    "extended_loading", ROOT / "tools" / "summarize_reflex_long_load.py")
loader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader
spec.loader.exec_module(loader)


def line(pc, n=1):
    return f"[reflex-mxtables-inner] pc={pc} hit={n}\n"


def test_many_decoder_loops_alone_do_not_mean_loaded():
    original = line("004ef52e", 32)
    extended = line("004ef52e", 512)
    report = loader.report(original, extended, 840)
    assert "NO DECODE RETURN OBSERVED" in report
    assert "progressed beyond the 60s control" in report


def test_actual_decoder_return_not_equivalent_to_loaded_resource():
    report = loader.report("", line("004f019e"), 840)
    assert "DECODER RETURN OBSERVED" in report
    assert "Original type-1 resource loader returned/completed: False" in report


def test_resource_status_completion_must_be_observed_explicitly():
    report = loader.report("", "[reflex-type1-single] pc=0084bfb8 hit=1\n", 840)
    assert "LOADER RETURN OBSERVED" in report


def test_empty_trace_reports_no_progress():
    assert "NO DECODE RETURN OBSERVED" in loader.report("", "", 840)


@pytest.mark.parametrize("seconds", [0, -100])
def test_invalid_window_fails(seconds):
    with pytest.raises(ValueError):
        loader.report("", "", seconds)
