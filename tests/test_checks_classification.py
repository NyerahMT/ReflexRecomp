"""Fast-path classification must never skip native validation for source changes."""
from pathlib import Path
import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "classify", ROOT / "tools" / "classify_checks.py")
classification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classification)


def test_only_generated_guest_trace_is_lightweight():
    assert not classification.native_required([
        "tools/patch_reflex_cached_loading_stages.py",
        "tests/test_cached_loading_stages.py",
        ".github/workflows/fast-iterate.yml",
    ])
    assert classification.is_cached_diagnostic_only(
        "tools/patch_reflex_cached_resource_find.py")
    assert not classification.is_cached_diagnostic_only(
        "runtime/reflex_compat.cpp")
    assert not classification.is_cached_diagnostic_only(
        "tools/patch_reflex_runtime.py")


def test_any_runtime_native_ios_or_unknown_change_requires_full_build():
    for path in (
        "runtime/reflex_compat.cpp",
        "runtime/reflex_d3d9_ffp_quad.h",
        "tools/patch_reflex_d3d9_ffp_quad.py",
        "tools/build.py",
        "tools/classify_checks.py",
        "tests/test_d3d9_half.py",
        ".github/workflows/checks.yml",
        ".github/workflows/ios-native.yml",
        "ios/ReflexApp.mm",
        "README.md",
        "unknown-folder/new-file",
    ):
        assert classification.native_required([
            "tools/patch_reflex_cached_loading_stages.py", path])


def test_unknown_empty_diff_rebuilds():
    assert classification.native_required([])
    assert classification.native_required([""])


def test_run_checks_workflow_has_single_pr_trigger_and_classification():
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    assert 'branches: ["main"]' in workflow
    assert "  pull_request:" in workflow
    assert "tools/classify_checks.py --base origin/main" in workflow
    assert "steps.native.outputs.native_required == 'true'" in workflow
    assert "cancel-in-progress: true" in workflow


def test_main_commit_classifies_first_parent_instead_of_always_native(monkeypatch, capsys):
    seen = []
    def changed(base, head):
        seen.append((base, head))
        return [".github/workflows/fast-iterate.yml",
                "tests/test_fast_iteration_performance.py"]
    monkeypatch.setattr(classification, "changed_files", changed)
    monkeypatch.setattr(sys, "argv", ["classify_checks.py", "--main"])
    assert classification.main() == 0
    assert seen == [("HEAD^", "HEAD")]
    assert "native_required=false" in capsys.readouterr().out


def test_main_diff_error_fails_closed(monkeypatch, capsys):
    def failed_diff(base, head):
        raise subprocess.CalledProcessError(1, "git diff")
    monkeypatch.setattr(classification, "changed_files", failed_diff)
    monkeypatch.setattr(sys, "argv", ["classify_checks.py", "--main"])
    assert classification.main() == 0
    assert "native_required=true" in capsys.readouterr().out


def test_main_with_runtime_edit_requires_native(monkeypatch, capsys):
    monkeypatch.setattr(classification, "changed_files",
                        lambda base, head: ["runtime/reflex_compat.cpp"])
    monkeypatch.setattr(sys, "argv", ["classify_checks.py", "--main"])
    assert classification.main() == 0
    assert "native_required=true" in capsys.readouterr().out
