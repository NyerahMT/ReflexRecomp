"""Asset-free tests for fixed-duration Mesa rasterizer A/B comparisons."""
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location(
    "mesa_compare", ROOT / "tools" / "compare_reflex_decoder_variants.py")
compare = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compare
spec.loader.exec_module(compare)


def reading(pc, n):
    return f"[reflex-mxtables-inner] pc={pc} hit={n}\n"


def test_increase_detected_at_same_duration():
    a = compare.sample(reading("004ef52e", 2) + reading("004ef3c1", 64))
    b = compare.sample(reading("004ef52e", 32) + reading("004ef3c1", 128))
    text = compare.report_variant(a, b, 60)
    assert "VARIANT REACHED MORE CHECKPOINTS" in text
    assert "PC 004ef52e: baseline>=2 lp1>=32 trend=up" in text


def test_equal_hit_counts_do_not_fabricate_improvement():
    a = compare.sample(reading("004ef52e", 2))
    b = compare.sample(reading("004ef52e", 2))
    result = compare.report_variant(a, b, 60)
    assert "NO MEASURED GAIN" in result
    assert "trend=equal" in result


def test_missing_shared_samples_are_inconclusive():
    a = compare.sample(reading("004ef3c1", 64))
    b = compare.sample(reading("004ef58a", 2))
    assert "INCONCLUSIVE" in compare.report_variant(a, b, 60)


def test_return_marker_captured_from_guest_type1_trace():
    a = compare.sample(reading("004ef52e", 2))
    b = compare.sample(reading("004ef52e", 2) +
                       "[reflex-type1-single] pc=0084bfb8 hit=1")
    result = compare.report_variant(a, b, 60)
    assert "Guest return/status 0084bfb8: baseline=0 lp1=1" in result


@pytest.mark.parametrize("invalid", [0, -1])
def test_nonpositive_window_rejected(invalid):
    sample = compare.sample("")
    with pytest.raises(ValueError):
        compare.report_variant(sample, sample, invalid)
