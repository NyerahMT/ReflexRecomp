"""Synthetic /proc tests, no game files or ptrace required."""
import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "native_sampler", ROOT / "tools" / "sample_reflex_native_threads.py")
sampler = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sampler
spec.loader.exec_module(sampler)


def fake_stat(tid, comm, state, user_ticks, system_ticks):
    # Remaining tokens start at Linux field #3: state at idx 0,
    # utime and stime at indices 11 and 12.
    fields = [state] + ["0"] * 10 + [str(user_ticks), str(system_ticks)]
    return f"{tid} ({comm}) " + " ".join(fields) + "\n"


def fixture(proc, pid=321, tid=444, user_ticks=120, state="S",
            comm="Reflex (worker)", wchan="futex_wait_queue"):
    base = proc / str(pid)
    task = base / "task" / str(tid)
    task.mkdir(parents=True, exist_ok=True)
    (task / "stat").write_text(fake_stat(tid, comm, state, user_ticks, 2))
    (task / "comm").write_text(comm + "\n")
    (task / "wchan").write_text(wchan + "\n")
    (base / "status").write_text("VmRSS:\t40960 kB\n")


def test_parse_linux_stat_handles_parentheses_in_comm():
    assert sampler.parse_stat(fake_stat(4, "(worker) pthread", "R", 50, 10)) == ("R", 60)


def test_snapshot_and_memory(tmp_path):
    fixture(tmp_path)
    data = sampler.read_snapshot(321, proc=tmp_path, elapsed=2.5)
    assert data.rss_kb == 40960
    assert data.threads[444].cpu_ticks == 122
    assert data.threads[444].state == "S"
    assert data.threads[444].wchan == "futex_wait_queue"


def test_disappeared_process_is_not_invented(tmp_path):
    assert sampler.read_snapshot(999, proc=tmp_path) is None


def test_thread_cpu_delta_and_wait_channel(tmp_path):
    fixture(tmp_path, user_ticks=100)
    before = sampler.read_snapshot(321, proc=tmp_path, elapsed=3.0)
    fixture_path = tmp_path / "321/task/444/stat"
    fixture_path.write_text(fake_stat(444, "worker", "R", 150, 2))
    after = sampler.read_snapshot(321, proc=tmp_path, elapsed=5.0)
    report = sampler.summary(after, before, tick_hz=100)
    assert "process_cpu=25.0%" in report
    assert "444/Reflex (worker):25.0%:R:futex_wait_queue" in report
    assert "rss=40.0MiB" in report


def test_new_thread_is_not_counted_without_prior_sample(tmp_path):
    fixture(tmp_path, user_ticks=500)
    before = sampler.Snapshot(1.0, {}, None)
    after = sampler.read_snapshot(321, proc=tmp_path, elapsed=2.0)
    assert "process_cpu=0.0%" in sampler.summary(after, before, 100)


def test_missing_wchan_reports_unknown(tmp_path):
    fixture(tmp_path)
    (tmp_path / "321/task/444/wchan").unlink()
    data = sampler.read_snapshot(321, proc=tmp_path)
    assert data.threads[444].wchan == "?"


@pytest.mark.parametrize("duration,interval", [(0, 1), (1, 0), (1, 2)])
def test_invalid_sampling_windows(tmp_path, duration, interval):
    with pytest.raises(ValueError):
        sampler.collect(123, seconds=duration, interval=interval, proc=tmp_path)


def test_summary_with_no_threads():
    report = sampler.summary(sampler.Snapshot(0, {}, None), None, 100)
    assert "native_threads=0" in report
    assert "initial-sample" in report
