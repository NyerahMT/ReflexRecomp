"""Keep cached compiled game objects exclusively in the private input repo."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github" / "workflows" / "fast-iterate.yml").read_text()


def test_private_warmed_compiler_cache_is_restored_and_saved():
    assert 'WARM_CCACHE_ASSET=$warm' in WORKFLOW
    assert '--pattern "$WARM_CCACHE_ASSET"' in WORKFLOW
    assert 'tar -xzf "$RUNNER_TEMP/reflex-warm-ccache/$WARM_CCACHE_ASSET"' in WORKFLOW
    assert 'gh release upload "$BASELINE_TAG" "$archive"' in WORKFLOW
    assert '--repo "$INPUT_REPO" --clobber' in WORKFLOW


def test_private_cache_upload_follows_successful_build_before_runtime():
    build = WORKFLOW.index("      - name: Build from cached translation")
    persist = WORKFLOW.index("      - name: Preserve warmed compiler cache in private build input")
    probe = WORKFLOW.index("      - name: Probe Reflex runtime gate")
    assert build < persist < probe
    cache_step = WORKFLOW[persist:probe]
    assert "if: steps.host.outcome == 'success'" in cache_step
    assert 'GH_TOKEN: ${{ secrets.REFLEX_INPUT_TOKEN }}' in cache_step
    assert 'tar -czf "$archive" -C "$GITHUB_WORKSPACE" ".ci-cache/ccache"' in cache_step
    assert "Could not save warmed compiler cache" in cache_step


def test_private_cache_does_not_leak_to_public_actions_artifacts():
    upload = WORKFLOW[WORKFLOW.index("      - name: Upload fast-path logs"):]
    assert "path: build/logs/" in upload
    assert "path: .ci-cache" not in upload
    assert "path: build/package/" not in upload
