"""Verify all Reflex kernel32 patch anchors against the pinned recomp-kit.

The fast full-game build takes substantial time. A one-space mismatch in an
injected source anchor once failed before compilation. This test statically
simulates all ordered kernel32 source replacements in the *actual pinned
version*, including idempotence of the patch marker.
"""
import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "tools" / "patch_reflex_runtime.py"
PINNED_KERNEL32 = ROOT / "kit" / "runtime" / "kernel32.cpp"


def test_pinned_kernel32_runtime_patch_anchors():
    if not PINNED_KERNEL32.is_file():
        pytest.skip("Pinned recomp-kit source not checked out")
    tree = ast.parse(PATCH.read_text())
    original = PINNED_KERNEL32.read_text()
    patched = original
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "replace_once":
            continue
        if len(node.args) != 4:
            continue
        target = node.args[0]
        if not isinstance(target, ast.Name) or target.id != "kernel32":
            continue
        old, new, marker = [ast.literal_eval(arg) for arg in node.args[1:]]
        assert patched.count(old) == 1, f"Missing or ambiguous pinned kernel32 anchor for {marker}"
        assert marker in new, f"Patch marker not present in replacement: {marker}"
        patched = patched.replace(old, new, 1)
        assert marker in patched
        count += 1
    assert count >= 6, "Unexpected loss of kernel32 event, wait or thread patches"
    assert "[reflex-thread] CreateThread start=" in patched
    assert "DatabaseThreadEvent" in patched
