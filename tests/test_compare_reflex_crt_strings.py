"""Deterministic guest-CRT performance comparison classification tests."""
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location(
    "crt_compare", ROOT / "tools" / "compare_reflex_crt_strings.py")
compare = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compare
spec.loader.exec_module(compare)


def line(pc, hit):
    return f"[reflex-mxtables-inner] pc={pc} hit={hit}\n"


def test_fast_opt_in_must_be_confirmed():
    raw = line("004ef52e", 2)
    assert "INCONCLUSIVE - fast CRT never initialized" in compare.report(raw, raw, 60)


def test_faster_variant_reaches_more_checkpoints():
    ref = line("004ef52e", 2)
    fast = "[reflex-crt-fast] enabled=1\n" + line("004ef52e", 12)
    result = compare.report(ref, fast, 60)
    assert "OPTIMIZED REACHED MORE SAMPLED CHECKPOINTS" in result


def test_same_visit_count_is_no_measured_gain():
    a = line("004ef52e", 12)
    assert "NO MEASURABLE THROUGHPUT GAIN" in compare.report(
        a, "[reflex-crt-fast] enabled=1\n" + a, 60)


def test_missing_candidate_decoder_produces_inconclusive():
    assert "INCONCLUSIVE - decoder checkpoints missing" in compare.report(
        line("004ef52e", 2), "[reflex-crt-fast] enabled=1\n", 60)


@pytest.mark.parametrize("seconds", [0, -1])
def test_bad_duration_fails(seconds):
    with pytest.raises(ValueError):
        compare.report("", "", seconds)
