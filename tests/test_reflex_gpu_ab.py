"""One-step GPU A/B classification. No Reflex binary, shaders, or GPU needed."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "reflex_gpu_ab", ROOT / "tools" / "analyze_reflex_gpu_ab.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BASE = (
    "[recomp] [reflex-gpu-ab] od=8 read_original=1 read_blend=1 "
    "read_direct=1 direct_rgb=255 direct_alpha=15 blend_rgb=15 "
    "original_rgb=15 direct_nonzero=11 original_nonzero=11 "
    "active=11 within2=11 max_blend_error=0 max_original_error=0 "
    "shader_alpha_low=8 shader_alpha_high=0 depth_detached=1"
)

def altered(**changes):
    parts = BASE.split(" ")
    return " ".join(
        k + "=" + str(changes[k]) if "=" in p and
        (k := p.split("=", 1)[0]) in changes else p for p in parts
    )

def test_batch_classifies_multiple_hypotheses():
    assert mod.classify(BASE)["status"] == "alpha_attenuation_consistent"
    assert mod.classify(altered(direct_rgb=15))["status"] == "fragment_output_dark"
    assert mod.classify(altered(max_blend_error=15))["status"] == "blend_math_mismatch"
    assert mod.classify(altered(max_original_error=15))["status"] == "replay_not_equivalent"
    assert mod.classify(altered(active=0))["status"] == "inconclusive_no_coverage"
    assert mod.classify(altered(read_direct=0))["status"] == "readback_failed"
    assert mod.classify(altered(blend_rgb=255, original_rgb=255))[
        "status"] == "other_pipeline_issue"

def test_earlier_unrelated_logs_are_ignored():
    assert mod.classify("nothing rendered")["status"] == "no_capture"
    assert mod.classify("[reflex-gpu-ab] od=8 read_original=1")[
        "status"] == "malformed_capture"
    assert mod.classify(BASE + "\n" + altered(direct_rgb=15))[
        "status"] == "fragment_output_dark"

def test_cli_writes_json_and_reports_missing_probes(tmp_path):
    import json
    import subprocess
    import sys
    log = tmp_path / "startup.log"
    output = tmp_path / "reports" / "gpu-ab.json"
    log.write_text(BASE + "\n")
    call = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "analyze_reflex_gpu_ab.py"),
         str(log), "--output", str(output)],
        capture_output=True, text=True)
    assert call.returncode == 0, call.stderr
    assert json.loads(output.read_text())["status"] == "alpha_attenuation_consistent"
    log.write_text("no draw eight\n")
    call = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "analyze_reflex_gpu_ab.py"),
         str(log), "--output", str(output)],
        capture_output=True, text=True)
    assert call.returncode == 1
    assert json.loads(output.read_text())["status"] == "no_capture"

def test_workflow_uses_short_run_and_no_long_load():
    yaml = (ROOT / ".github" / "workflows" / "fast-iterate.yml").read_text()
    assert "contains(github.event.head_commit.message, '[gpu-ab]')" in yaml
    assert "REFLEX_GPU_AB=" in yaml
    assert "REFLEX_BRIGHTNESS_PROBE=" in yaml
    assert "tools/analyze_reflex_gpu_ab.py" in yaml
    assert "reflex-gpu-ab-classification.json" in yaml
    # 840s qualification is independently gated solely on [long-load].
    qualification = yaml.split(
        "- name: Qualify original MXTables loading through extended 14-minute run", 1)[1]
    assert "contains(github.event.head_commit.message, '[long-load]')" in qualification
    assert "[gpu-ab]" not in qualification.split("run: |", 1)[0]
