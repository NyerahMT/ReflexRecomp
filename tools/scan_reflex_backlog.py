#!/usr/bin/env python3
"""Evidence-based Reflex compatibility inventory from static and runtime probes.

The scan is scoped to cached translated sites and the guest paths actually run.
It deliberately does not claim to count all game bugs, estimate release
readiness, or export game assets. Accepts optional/missing logs after CI errors.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

SITE = re.compile(r"^([0-9a-fA-F]{8})\s+(\S+)\s+(chunk_[\w.]+)$", re.M)
MISSING_IMPORT = re.compile(r"unimplemented import\s+([^\r\n]+?): returning 0")
BAD_ARITY = re.compile(r"([^\s]+) has an unknown stdcall argument count")
BAD_CALL = re.compile(r"call to unknown target\s+([0-9a-fA-F]{8}).*?return=([0-9a-fA-F]{8})")
SEH = re.compile(r"SEH: unhandled exception[^\r\n]*?code=([0-9a-fA-F]{8})")
DRAW = re.compile(
    r"\[reflex-frame\] shaderless-skip n=(\d+) "
    r"fvf=([0-9a-fA-F]{8}) decl=(\d+) vs=(\d+) ps=(\d+)"
)
FAMILIES = {
    "SIMD reciprocal/root": {"RCPPS", "RCPSS", "RSQRTPS", "RSQRTSS"},
    "SIMD conversions/comparison": {"CVTPI2PS", "CVTPS2DQ", "CVTDQ2PS", "PCMPGTD"},
    "SIMD register lanes": {"MOVLHPS", "MOVHLPS"},
}


def scan_static(path: Path | None) -> dict:
    unavailable = {"available": False, "sites": None, "identified": None,
                   "unidentified": None, "instruction_types": {},
                   "families": [], "other_types": {}}
    if path is None or not path.is_file():
        return unavailable
    content = path.read_text(errors="replace")
    sites = {pc.lower(): op.upper() for pc, op, _ in SITE.findall(content)}
    declared = re.search(r"Unmodelled guest instruction sites: (\d+)", content)
    if declared is None or len(sites) != int(declared.group(1)):
        return unavailable
    counts = Counter(sites.values())
    unknown = counts.pop("<NOT-MAPPED>", 0)
    groups = []
    used = set()
    for name, members in FAMILIES.items():
        part = {op: n for op, n in sorted(counts.items()) if op in members}
        if part:
            groups.append({"name": name, "sites": sum(part.values()),
                           "types": len(part), "mnemonics": part})
            used.update(part)
    return {"available": True, "sites": len(sites),
            "identified": len(sites) - unknown, "unidentified": unknown,
            "instruction_types": dict(sorted(counts.items())),
            "families": sorted(groups, key=lambda g: -g["sites"]),
            "other_types": {name: n for name, n in sorted(counts.items())
                            if name not in used}}


def scan_log(path: Path) -> dict:
    data = path.read_text(errors="replace")
    imports = Counter(m.strip() for m in MISSING_IMPORT.findall(data))
    arity = Counter(m.strip() for m in BAD_ARITY.findall(data))
    calls = Counter(f"{target.lower()}@{ret.lower()}"
                    for target, ret in BAD_CALL.findall(data))
    errors = Counter(f"0x{code.lower()}" for code in SEH.findall(data))
    draws = {}
    for n, fvf, decl, vs, ps in DRAW.findall(data):
        shape = f"fvf={fvf.lower()} decl={decl} vs={vs} ps={ps}"
        draws[shape] = max(draws.get(shape, 0), int(n))
    return {"bytes": len(data), "imports": dict(sorted(imports.items())),
            "unknown_arities": dict(sorted(arity.items())),
            "bad_calls": dict(sorted(calls.items())),
            "unhandled_exceptions": dict(sorted(errors.items())),
            "shaderless_shapes": dict(sorted(draws.items())),
            "has_present": "[reflex-frame] present" in data}


def scan(traps: Path | None, runtime: list[Path]) -> dict:
    static = scan_static(traps)
    log_reports = {str(p): scan_log(p) for p in runtime if p.is_file()}
    agg = {k: Counter() for k in
           ("imports", "unknown_arities", "bad_calls", "unhandled_exceptions")}
    draws = {}
    for r in log_reports.values():
        for name, counter in agg.items():
            counter.update(r[name])
        for shape, n in r["shaderless_shapes"].items():
            draws[shape] = max(draws.get(shape, 0), n)
    observed = {k: dict(sorted(v.items())) for k, v in agg.items()}
    observed["shaderless_shapes"] = dict(sorted(draws.items()))
    summary = {
        "static_sites": static["sites"],
        "identified_instruction_types": (len(static["instruction_types"])
                                         if static["available"] else None),
        "unidentified_static_sites": static["unidentified"],
        "batchable_instruction_families": len(static["families"]),
        "runtime_imports_reached": len(observed["imports"]),
        "unknown_import_arities_reached": len(observed["unknown_arities"]),
        "bad_call_site_pairs_reached": len(observed["bad_calls"]),
        "shaderless_render_shapes_observed": len(draws),
        "logs_scanned": len(log_reports),
        "logs_requested": len(runtime),
    }
    return {"schema_version": 1, "summary": summary, "static": static,
            "per_log": log_reports, "runtime": observed,
            "limitations": [
                "Unexecuted guest paths remain unknown; these are lower bounds, not total bugs.",
                "Static untranslated sites are candidates, not proven gameplay blockers.",
                "Missing imports, bad calls, and exceptions may share a single root cause.",
                "Instruction-family batching is a prospect, not a guarantee.",
                "Frame presentation or successful CI does not prove a functional menu.",
                "No original game binaries or proprietary disassembly are included.",
            ]}


def render(report: dict) -> str:
    s, t, rt = report["summary"], report["static"], report["runtime"]
    val = lambda key: str(s[key]) if s[key] is not None else "not scanned"
    lines = ["# Reflex compatibility inventory", "",
             "**Scope:** cached translation + observed guest runtime logs only.",
             "**Not a count of all remaining bugs or a release-readiness percentage.**",
             "", "## Totals", "",
             f"- Unmodeled static x86 sites: **{val('static_sites')}**",
             f"- Distinct identified instruction types: **{val('identified_instruction_types')}**",
             f"- Unidentified instruction sites: **{val('unidentified_static_sites')}**",
             f"- Observed missing guest imports: **{s['runtime_imports_reached']}**",
             f"- Observed unknown stdcall arities: **{s['unknown_import_arities_reached']}**",
             f"- Distinct invalid indirect call-site pairs: **{s['bad_call_site_pairs_reached']}**",
             f"- Distinct shaderless-render shapes: **{s['shaderless_render_shapes_observed']}**",
             f"- Scanned **{s['logs_scanned']} of {s['logs_requested']}** supplied runtime logs.",
             "", "## Potential batch fixes (not confirmed blockers)", ""]
    if t["available"]:
        lines += [f"- {g['name']}: **{g['sites']} sites**, {g['types']} instruction types"
                  for g in t["families"]]
        lines += [f"- {name}: **{n} sites**"
                  for name, n in t["other_types"].items()]
    else:
        lines.append("- Translation audit unavailable.")
    lines += ["", "## Missing imports observed in executions", ""]
    lines += [f"- `{name}`: {n} occurrence(s)"
              for name, n in rt["imports"].items()] or [
                  "- None in supplied logs; other code paths remain untested."]
    lines += ["", "## Invalid guest indirect calls observed", ""]
    lines += [f"- `target@return={name}`: {n} occurrence(s)"
              for name, n in rt["bad_calls"].items()] or [
                  "- None in supplied logs; other code paths remain untested."]
    lines += ["", "## Fixability guidance", "",
              "1. Fix missing imports using correct guest ABI, output validation, and honest service semantics.",
              "2. Analyze invalid call targets alongside missing imports; they may be the same fault.",
              "3. Batch compatible untranslated instructions by semantic family only after testing.",
              "4. Identify unmapped instruction sites; track reachable ones separately.",
              "5. Diagnose shaderless draws using framebuffer captures, not present counts.",
              "", "## Important limitations", ""]
    lines += ["- " + item for item in report["limitations"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trap-report", type=Path)
    parser.add_argument("--runtime", action="append", type=Path, default=[])
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = scan(args.trap_report, args.runtime)
    output = render(report)
    print(output, end="")
    for path, content in ((args.json, json.dumps(report, indent=2, sort_keys=True)+"\n"),
                          (args.markdown, output)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)


if __name__ == "__main__":
    main()
