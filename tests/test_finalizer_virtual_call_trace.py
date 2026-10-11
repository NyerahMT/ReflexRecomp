"""Test sampled indirect-call tracing of post-Intro resource finalization."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_call_trace.py"
SPEC = importlib.util.spec_from_file_location("reflex_call_trace", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def fixture():
    return (
        '#include <stdint.h>\n'
        '#include <stdbool.h>\n'
        '#include <stdio.h>\n'
        '#define GUEST_SIZE 0x20000000u\n'
        '#define R_EAX 0\n#define R_ECX 1\n#define R_EDX 2\n'
        '#define R_EBX 3\n#define R_ESP 4\n#define R_ESI 6\n#define R_EDI 7\n'
        'typedef struct X86 { uint32_t r[8]; } X86;\n'
        'static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n'
        'void recomp_call(X86 *c, uint32_t target)\n'
        '{\n'
        '    (void)c; (void)target;\n'
        '}\n'
    )


def test_finalizer_call_site_diagnostics_are_strict_c11(tmp_path, monkeypatch):
    gen = tmp_path / "table.c"
    gen.write_text(fixture())
    monkeypatch.setattr(mod, "TABLE", gen)
    mod.main()
    patched = gen.read_text()
    assert "reflex-finalizer-vcall-v1" in patched
    assert "trace_ret == 0x00543d68u" in patched
    assert "trace_ret == 0x00543d86u" in patched
    assert '"[reflex-finalizer-call] phase=%s' in patched
    assert 'valid_stack ? rd32(trace_esp + 4u) : 0u' in patched
    mod.main()
    assert gen.read_text() == patched

    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not cc:
        pytest.skip("No C compiler")
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
         str(gen)], check=True, capture_output=True, text=True,
    )


def test_missing_or_duplicate_translation_dispatch_fails_closed(tmp_path, monkeypatch):
    gen = tmp_path / "table.c"
    monkeypatch.setattr(mod, "TABLE", gen)
    with pytest.raises(SystemExit, match="missing cached generated table"):
        mod.main()
    gen.write_text("void not_dispatch(void) {}")
    with pytest.raises(SystemExit, match="expected exactly one recomp_call"):
        mod.main()
