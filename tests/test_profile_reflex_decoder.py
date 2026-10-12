"""Artifact-free, deterministic tests for Reflex decoder throughput comparison."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "decoder_profile", ROOT / "tools" / "profile_reflex_decoder.py"
)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_uses_max_power_of_two_sample_not_line_count():
    t = "\n".join(
        f"[reflex-mxtables-inner] pc=004ef52e hit={n}" for n in (1, 2, 8, 16, 32)
    )
    data = module.sample(t)
    assert data.unique_decoder_pcs == 1
    assert data.max_hit_by_pc["004ef52e"] == 32


def test_reports_same_loop_progress_after_longer_run():
    a = module.sample(
        "[reflex-mxtables-inner] pc=004ef52e hit=2\n"
        "[reflex-mxtables-inner] pc=004ef58a hit=2"
    )
    b = module.sample(
        "[reflex-mxtables-inner] pc=004ef52e hit=2\n"
        "[reflex-mxtables-inner] pc=004ef58a hit=2"
    )
    result = module.report(a, b, 15, 60)
    assert "NO MEASURABLE ADVANCE" in result
    assert "PC 004ef52e: control_hits>=2 extended_hits>=2" in result


def test_reports_actual_increment_even_without_more_logged_lines():
    baseline = module.sample(
        "[reflex-mxtables-inner] pc=004ef52e hit=8"
    )
    extended = module.sample(
        "[reflex-mxtables-inner] pc=004ef52e hit=16"
    )
    assert "ADVANCED" in module.report(baseline, extended, 15, 60)


def test_unknown_when_diagnostics_absent():
    a = module.sample("[reflex-frame] present n=16\n")
    assert "INCONCLUSIVE" in module.report(a, a, 15, 60)


def test_return_marker_does_not_get_confused_with_other_pc():
    a = module.sample("[reflex-type1-single] pc=0084bfb8 hit=1")
    b = module.sample("[reflex-type1-single] pc=0084bfb8 hit=1")
    result = module.report(a, b, 15, 60)
    assert "Return/status PC 0084bfb8: control=1 extended=1" in result


@pytest.mark.parametrize("seconds", [(0, 60), (15, 15), (70, 60)])
def test_invalid_windows_rejected(seconds):
    with pytest.raises(ValueError):
        module.report(module.sample(""), module.sample(""), *seconds)
