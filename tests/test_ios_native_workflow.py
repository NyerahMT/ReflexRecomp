"""iOS CI must compile actual translated game and keep it private."""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/ios-native.yml").read_text()


def test_real_original_game_ios_compile():
    assert 'runs-on: macos-15' in WORKFLOW
    assert 'test -s build/recomp/gen/table.c' in WORKFLOW
    assert '--target ios --no-install --team 0000000000 --jobs 6' in WORKFLOW
    assert '--stub' not in WORKFLOW
    assert 'CODE_SIGNING_ALLOWED=NO' in WORKFLOW
    assert 'REFLEX_INPUT_TOKEN' in WORKFLOW


def test_do_not_publish_proprietary_iOS_game():
    artifacts = WORKFLOW[WORKFLOW.index('      - name: Upload diagnostics only'):]
    assert 'build/logs/native-arm64-ios.log' in artifacts
    assert 'build/recomp/gen' not in artifacts
    assert 'build/ios' not in artifacts
    assert 'Game-Core.zip' not in artifacts


def test_ios_build_stages_matching_private_database_payloads():
    assert '--pattern "Archive.4.zip"' in WORKFLOW
    assert '--pattern "Archive.3.zip"' in WORKFLOW
    assert 'unzip -p "$RUNNER_TEMP/input/Archive.3.zip" ' in WORKFLOW
    assert '"$game_root/Database/MXUI.dx9.package"' in WORKFLOW
    assert 'python3 tools/verify_ios_reflex_assets.py' in WORKFLOW
    assert '--app "$app"' in WORKFLOW
    assert "required_assets_staged=" in WORKFLOW
    assert "Fail if iOS bundle lacks original startup assets" in WORKFLOW
