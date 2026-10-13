"""Asset-free tests for the compatibility backlog: no false total-bug claims."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "scan_reflex_backlog.py"
SPEC = importlib.util.spec_from_file_location("scan_reflex_backlog", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def fixture_traps(path):
    path.write_text(
        "Reflex cached-translation unsupported-instruction inventory\n"
        "Unmodelled guest instruction sites: 6\n"
        "Resolved guest mnemonics: 5\n"
        "\nSites (address | mnemonic | generated chunk)\n"
        "00410000  RCPPS  chunk_001.c\n"
        "00410001  RCPPS  chunk_001.c\n"
        "00410002  RSQRTPS  chunk_001.c\n"
        "00410003  MOVLHPS  chunk_001.c\n"
        "00410004  CVTPS2DQ  chunk_001.c\n"
        "00410005  <not-mapped>  chunk_001.c\n"
    )


def test_static_opcode_inventory_batches_related_sites(tmp_path):
    trap = tmp_path / "traps.txt"
    fixture_traps(trap)
    report = audit.scan_static(trap)
    assert report["available"]
    assert report["sites"] == 6
    assert report["identified"] == 5
    assert report["unidentified"] == 1
    assert len(report["instruction_types"]) == 4
    assert {x["name"]: x["sites"] for x in report["families"]} == {
        "SIMD reciprocal/root": 3,
        "SIMD conversions/comparison": 1,
        "SIMD register lanes": 1,
    }


def test_invalid_trap_counts_fail_closed(tmp_path):
    file = tmp_path / "bad.txt"
    fixture_traps(file)
    file.write_text(file.read_text().replace("sites: 6", "sites: 900"))
    report = audit.scan_static(file)
    assert not report["available"]
    assert report["sites"] is None


def test_runtime_evidence_is_deduplicated_and_not_confused_with_root_cause(tmp_path):
    log = tmp_path / "runtime-long-load.log"
    log.write_text(
        "[recomp] unimplemented import fmodexL.dll!?createSound: returning 0\n"
        "[recomp] unimplemented import fmodexL.dll!?createSound: returning 0\n"
        "[recomp] fmodexL.dll!?createSound has an unknown stdcall argument count\n"
        "[recomp] SEH: unhandled exception record=02000000 code=c0000005 flags=00000000\n"
        "[recomp] call to unknown target 00000000 "
        "(ESP=00001000, return=008067fd, EAX=0): returning 0\n"
        "[recomp] [reflex-frame] shaderless-skip n=4 "
        "fvf=00000000 decl=7220 vs=0 ps=0 prim=5 count=2\n"
        "[recomp] [reflex-frame] shaderless-skip n=32 "
        "fvf=00000000 decl=7220 vs=0 ps=0 prim=5 count=2\n"
    )
    report = audit.scan(None, [log, tmp_path / "missing.log"])
    assert report["summary"]["static_sites"] is None
    assert report["summary"]["logs_scanned"] == 1
    assert report["summary"]["logs_requested"] == 2
    assert report["summary"]["runtime_imports_reached"] == 1
    assert report["summary"]["unknown_import_arities_reached"] == 1
    assert report["summary"]["bad_call_site_pairs_reached"] == 1
    assert report["summary"]["shaderless_render_shapes_observed"] == 1
    assert report["runtime"]["imports"]["fmodexL.dll!?createSound"] == 2
    assert report["runtime"]["shaderless_shapes"]["fvf=00000000 decl=7220 vs=0 ps=0"] == 32
    assert "not a count of all remaining bugs" in audit.render(report).lower()


def test_static_file_absent_does_not_fabricate_zero_issues(tmp_path):
    report = audit.scan(tmp_path / "unknown.txt", [])
    assert report["summary"]["static_sites"] is None
    assert report["summary"]["runtime_imports_reached"] == 0
    assert "not scanned" in audit.render(report)
