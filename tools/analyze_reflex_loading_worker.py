#!/usr/bin/env python3
"""Evidence-only trace summary of Reflex's suspended loading worker.

Do not conflate no log line with never scheduled; all fields are observed
facts. This does not synthesize thread resume/event signal or alter execution.
"""
from pathlib import Path
import argparse
import re

CREATE = re.compile(r"\[reflex-thread\] CreateThread start=([0-9a-fA-F]+).*?handle=([0-9a-fA-F]+) tid=(\d+) suspended=(\d+)")
RESUME = re.compile(r"\[reflex-thread\] ResumeThread handle=([0-9a-fA-F]+) tid=(\d+) start=([0-9a-fA-F]+) previous=(-?\d+) after=(-?\d+)")
ENTER = re.compile(r"\[reflex-loading-worker\] enter tid=(\d+) start=([0-9a-fA-F]+)")
EXIT = re.compile(r"\[reflex-loading-worker\] exit tid=(\d+) result=([0-9a-fA-F]+)")
EVENT = re.compile(r"\[reflex-sync\] CreateEventA name=LoadingThreadEvent handle=([0-9a-fA-F]+)")
WAIT = re.compile(r"\[reflex-sync\] WaitForSingleObject enter tid=(\d+) handle=([0-9a-fA-F]+)")
SIGNAL = re.compile(r"\[reflex-sync\] SetEvent handle=([0-9a-fA-F]+)")
START = 0x00760400


def inspect(text: str) -> dict:
    out = dict(created=None, suspended=None, resumed=0, ready=None,
               entered=False, exited=False, loading_event=None,
               waits=0, event_signals=0)
    loading_handle = None
    lines = text.splitlines()
    # Pass 1: resolve event handle regardless of log order.
    for line in lines:
        match = EVENT.search(line)
        if match:
            loading_handle = int(match[1], 16)
            out["loading_event"] = f"{loading_handle:08x}"
            break

    for line in lines:
        if (m := CREATE.search(line)) and int(m[1], 16) == START:
            out["created"] = f"{int(m[2], 16):08x}"
            out["suspended"] = int(m[4])
        if (m := RESUME.search(line)) and int(m[3], 16) == START:
            out["resumed"] += 1
            out["ready"] = int(m[5]) == 0
        if (m := ENTER.search(line)) and int(m[2], 16) == START:
            out["entered"] = True
        if EXIT.search(line):
            out["exited"] = True
        if loading_handle is not None:
            if (m := WAIT.search(line)) and int(m[2], 16) == loading_handle and m[1] == "1":
                out["waits"] += 1
            if (m := SIGNAL.search(line)) and int(m[1], 16) == loading_handle:
                out["event_signals"] += 1
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    result = inspect(parser.parse_args().log.read_text(errors="replace"))
    print("Reflex loading worker lifecycle (None = unobserved):")
    for k,v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
