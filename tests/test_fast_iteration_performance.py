"""Keep quick original-game graphics probes fast without weakening native checks."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FAST = (ROOT / ".github/workflows/fast-iterate.yml").read_text()
CHECKS = (ROOT / ".github/workflows/checks.yml").read_text()
GPU_AB_GUARD = "github.event_name != 'push' || !contains(github.event.head_commit.message, '[gpu-ab]')"


def step_section(text, name):
    marker = "      - name: " + name + "\n"
    assert text.count(marker) == 1
    tail = text.split(marker, 1)[1]
    return tail.split("\n      - name: ", 1)[0]


def test_unrelated_expensive_loader_analysis_skipped_only_for_gpu_ab():
    for name in (
        "Inspect original type-1 loader guest instructions",
        "Audit cached translation opcode coverage",
        "Classify remaining unknown guest opcodes",
        "Compare exact localized Intro lookup (diagnostic only)",
        "Inventory Reflex compatibility backlog",
    ):
        section = step_section(FAST, name)
        assert GPU_AB_GUARD in section.split("run:", 1)[0], name
    assert "always() &&" in step_section(
        FAST, "Inventory Reflex compatibility backlog").split("run:", 1)[0]


def test_gpu_ab_still_builds_and_runs_real_game():
    for name in (
        "Patch Reflex runtime compatibility",
        "Download private Reflex core and recomp baseline",
        "Instrument cached runtime frontier",
        "Build from cached translation",
        "Probe Reflex runtime gate",
        "Profile MXTables decoder for 60 seconds",
        "Classify original shader-vs-blending GPU A/B",
        "Upload fast-path logs",
        "Fail if host build failed",
        "Fail if runtime gate exited early",
    ):
        assert "      - name: " + name + "\n" in FAST, name
    assert "contains(github.event.head_commit.message, '[gpu-ab]')" in step_section(
        FAST, "Classify original shader-vs-blending GPU A/B")
    assert "tools/analyze_reflex_gpu_ab.py" in FAST
    assert "840s" in step_section(
        FAST, "Qualify original MXTables loading through extended 14-minute run")
    assert "[long-load]" in step_section(
        FAST, "Qualify original MXTables loading through extended 14-minute run").split("run:", 1)[0]


def test_native_scaffold_is_avoided_only_for_classified_changes():
    assert "python3 tools/classify_checks.py --main" in CHECKS
    section = step_section(CHECKS, "Install Linux build prerequisites")
    assert "runner.os == 'Linux' && steps.native.outputs.native_required == 'true'" in section
    for step in ("Stub native configure/build", "Unsigned iOS stub compile"):
        assert "steps.native.outputs.native_required == 'true'" in step_section(
            CHECKS, step).split("run:", 1)[0]
    # Every run still performs the complete Python + kit regression suite.
    assert "-m pytest -q tests" in step_section(
        CHECKS, "Kit tests and Reflex config tests")
