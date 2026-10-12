"""Prevent a full Reflex build from missing MSVCR90 CRT compatibility headers."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "tools" / "patch_reflex_runtime.py"
spec = importlib.util.spec_from_file_location("reflex_patch", PATCHER)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def test_stage_both_compat_headers_atomically_and_idempotently(tmp_path):
    sources = tmp_path / "src"
    kit = tmp_path / "kit"
    sources.mkdir()
    kit.mkdir()
    numeric = sources / "reflex_crt_numeric.h"
    wide = sources / "reflex_crt_wide_format.h"
    fast = sources / "reflex_crt_fast_strings.h"
    numeric.write_text("numeric content\n")
    with pytest.raises(SystemExit, match="reflex_crt_wide_format.h"):
        patch.stage_compat_headers(kit, numeric, wide)
    assert not list(kit.iterdir()), "A failed preflight must not partially stage files"

    wide.write_text("wide format content\n")
    with pytest.raises(SystemExit, match="reflex_crt_fast_strings.h"):
        patch.stage_compat_headers(kit, numeric, wide, fast)
    assert not list(kit.iterdir())
    fast.write_text("fast string content\n")
    patch.stage_compat_headers(kit, numeric, wide, fast)
    assert (kit / numeric.name).read_text() == "numeric content\n"
    assert (kit / wide.name).read_text() == "wide format content\n"
    patch.stage_compat_headers(kit, numeric, wide, fast)
    assert (kit / fast.name).read_text() == "fast string content\n"
    assert len(list(kit.iterdir())) == 3


def test_every_local_crt_header_in_compat_cpp_is_staged():
    source = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    headers = ("reflex_crt_numeric.h", "reflex_crt_wide_format.h", "reflex_crt_fast_strings.h")
    for header in headers:
        assert f'#include "{header}"' in source
        assert (ROOT / "runtime" / header).is_file()
    assert "stage_compat_headers(KIT / \"runtime\")" in PATCHER.read_text()
    assert {patch.NUMERIC_HEADER.name, patch.WIDE_FORMAT_HEADER.name, patch.FAST_STRINGS_HEADER.name} == set(headers)
