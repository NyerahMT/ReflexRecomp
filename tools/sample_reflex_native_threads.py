#!/usr/bin/env python3
"""Read-only native CPU / scheduler samples during Reflex startup on Linux.

The original MXTables parser stays inside the translated decoder for >=60s.
Per-instruction logs establish that it advances, but not whether it is doing
CPU work, waiting on a lock, or being starved by another native thread.

This sampler reads /proc/<game_pid>/task/<tid>/{stat,comm,wchan} and
/proc/<game_pid>/status. It never ptraces, pauses or writes to the game.
The host OS may redact wchan; report '?' without treating it as a stall.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import os
import re
import time


@dataclass(frozen=True)
class Thread:
    tid: int
    name: str
    state: str
    cpu_ticks: int
    wchan: str


@dataclass(frozen=True)
class Snapshot:
    elapsed: float
    threads: dict[int, Thread]
    rss_kb: int | None


def parse_stat(content: str) -> tuple[str, int]:
    """Extract state + utime/stime, accounting for parentheses in comm."""
    end = content.rfind(") ")
    if end < 0:
        raise ValueError("Malformed /proc stat comm")
    fields = content[end + 2:].split()  # Field #3 (state) onward.
    if len(fields) < 13:
        raise ValueError("Missing /proc stat CPU fields")
    state = fields[0]
    if len(state) != 1:
        raise ValueError("Malformed /proc stat state")
    return state, int(fields[11]) + int(fields[12])


def read_snapshot(pid: int, *, proc: Path = Path("/proc"),
                  elapsed: float = 0.0) -> Snapshot | None:
    base = proc / str(pid)
    task_dir = base / "task"
    if not task_dir.is_dir():
        return None
    result: dict[int, Thread] = {}
    for task in sorted(task_dir.iterdir(), key=lambda path: path.name):
        if not task.name.isdecimal():
            continue
        try:
            state, ticks = parse_stat((task / "stat").read_text())
            name = (task / "comm").read_text().strip()[:40]
            try:
                wchan = (task / "wchan").read_text().strip()
            except OSError:
                wchan = "?"
        except (OSError, ValueError):
            # Threads can disappear while we walk /proc; don't invent data.
            continue
        tid = int(task.name)
        result[tid] = Thread(tid, name, state, ticks, wchan or "?")
    try:
        status = (base / "status").read_text()
        match = re.search(r"(?m)^VmRSS:\s*(\d+)\s+kB$", status)
        rss_kb = int(match[1]) if match else None
    except OSError:
        rss_kb = None
    return Snapshot(elapsed, result, rss_kb)


def summary(current: Snapshot, prior: Snapshot | None,
            tick_hz: int) -> str:
    if tick_hz <= 0:
        raise ValueError("Invalid /proc clock tick frequency")
    elapsed = (current.elapsed - prior.elapsed) if prior else 0.0
    states: dict[str, int] = {}
    for t in current.threads.values():
        states[t.state] = states.get(t.state, 0) + 1
    state_label = ",".join(f"{key}:{states[key]}" for key in sorted(states))
    usage: list[tuple[float, Thread]] = []
    if prior is not None and elapsed > 0:
        for tid, t in current.threads.items():
            old = prior.threads.get(tid)
            if old is None:
                continue  # Cannot safely estimate a newly-created thread's CPU.
            ticks = max(t.cpu_ticks - old.cpu_ticks, 0)
            usage.append((100.0 * ticks / tick_hz / elapsed, t))
    usage.sort(key=lambda item: (-item[0], item[1].tid))
    top = " ".join(
        f"{t.tid}/{t.name}:{cpu:.1f}%:{t.state}:{t.wchan}"
        for cpu, t in usage[:8]
    ) if usage else "initial-sample"
    total = sum(x[0] for x in usage)
    rss = f"{current.rss_kb / 1024:.1f}MiB" if current.rss_kb is not None else "?"
    return (
        f"t={current.elapsed:.1f}s native_threads={len(current.threads)} "
        f"states={state_label or '?'} process_cpu={total:.1f}% "
        f"rss={rss} top={top}"
    )


def collect(pid: int, *, seconds: float, interval: float,
            proc: Path = Path("/proc"),
            clock=time.monotonic, sleep=time.sleep) -> list[str]:
    if seconds <= 0 or interval <= 0 or seconds < interval:
        raise ValueError("Require positive duration >= interval")
    if pid <= 0:
        raise ValueError("Invalid process ID")
    tick_hz = os.sysconf("SC_CLK_TCK")
    out = [f"Read-only Reflex /proc samples pid={pid}, duration={seconds}s, "
           f"interval={interval}s (CPU percent is per one logical core)."]
    start = clock()
    last: Snapshot | None = None
    i = 0
    while True:
        elapsed = clock() - start
        snapshot = read_snapshot(pid, proc=proc, elapsed=elapsed)
        if snapshot is None:
            out.append(f"t={elapsed:.1f}s process-exited-or-inaccessible")
            break
        out.append(summary(snapshot, last, tick_hz))
        last = snapshot
        i += 1
        if i * interval > seconds:
            break
        sleep(max(0.0, start + i * interval - clock()))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--seconds", type=float, default=26.0)
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    lines = collect(args.pid, seconds=args.seconds, interval=args.interval)
    for line in lines:
        print(line, flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
