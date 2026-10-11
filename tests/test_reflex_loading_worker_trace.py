"""Loading worker scheduling trace must report observations, not fake progress."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "analyze_reflex_loading_worker.py"
PATCH = ROOT / "tools" / "patch_reflex_runtime.py"
spec = importlib.util.spec_from_file_location("worker_trace", SCRIPT)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def test_detect_loading_event_never_signalled():
    log = """
[reflex-sync] CreateEventA name=LoadingThreadEvent handle=000100d0 manual=1 initial=0 handles=52
[reflex-thread] CreateThread start=00760400 param=0120df50 flags=00000004 handle=0001011c tid=22 suspended=1
[reflex-sync] WaitForSingleObject enter tid=1 handle=000100d0 guest_global=000100f0 valid=1
[reflex-sync] WaitForSingleObject exit tid=1 handle=000100d0 result=00000102
[reflex-sync] WaitForSingleObject enter tid=1 handle=000100d0 guest_global=000100f0 valid=1
"""
    result = trace.inspect(log)
    assert result["created"] == "0001011c"
    assert result["suspended"] == 1
    assert result["resumed"] == 0
    assert result["ready"] is None
    assert result["entered"] is False
    assert result["exited"] is False
    assert result["waits"] == 2
    assert result["event_signals"] == 0


def test_count_actual_resume_execution_and_signalling():
    log = """
[reflex-thread] CreateThread start=00760400 param=0120df50 flags=00000004 handle=0001011c tid=22 suspended=1
[reflex-thread] ResumeThread handle=0001011c tid=22 start=00760400 previous=1 after=0
[reflex-loading-worker] enter tid=22 start=00760400 param=0120df50 suspended=0
[reflex-sync] SetEvent handle=000100d0 guest_global=000100f0 valid=1
[reflex-sync] CreateEventA name=LoadingThreadEvent handle=000100d0 manual=1 initial=0 handles=52
[reflex-loading-worker] exit tid=22 result=00000000
"""
    result = trace.inspect(log)
    assert result["resumed"] == 1
    assert result["ready"] is True
    assert result["entered"] is True
    assert result["exited"] is True
    assert result["event_signals"] == 1
    assert result["waits"] == 0


def test_absent_information_is_unknown_not_a_fake_failure():
    result = trace.inspect("normal, uninstrumented startup")
    assert result["created"] is None
    assert result["suspended"] is None
    assert result["ready"] is None
    assert result["loading_event"] is None
    assert not result["entered"]


def test_worker_lifecycle_anchors_present_in_pinned_kit_patcher():
    patch = PATCH.read_text()
    assert '[reflex-thread] ResumeThread handle=' in patch
    assert '[reflex-loading-worker] enter' in patch
    assert '[reflex-loading-worker] exit tid=' in patch
    assert '0x00760400u' in patch
