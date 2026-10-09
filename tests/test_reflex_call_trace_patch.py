"""Regression test: injected trace strings must remain valid C source."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "patch_reflex_call_trace.py"
SPEC = importlib.util.spec_from_file_location("reflex_call_trace_patch", SCRIPT)
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


def test_virtual_lookup_trace_uses_c_escaped_newline(tmp_path):
    table = tmp_path / "table.c"
    table.write_text(
        '#include <stdint.h>\n#include <stdio.h>\n'
        'struct X86;\n'
        'void recomp_call(X86 *c, uint32_t target)\n{\n'
        '  (void)c; (void)target;\n}\n'
    )
    old_table = patcher.TABLE
    try:
        patcher.TABLE = table
        patcher.main()
        generated = table.read_text()
        assert '[reflex-ui-lookup]' in generated
        assert '[reflex-queue]' in generated
        assert 'target == 0x0084c190u' in generated
        assert 'q_n <= 32 || (q_n & (q_n - 1)) == 0' in generated
        assert 'manager <= GUEST_SIZE - 0xfcu' in generated
        assert 'first_key <= GUEST_SIZE - 4u' in generated
        assert 'gm_valid(' not in generated
        assert 'trace_esp <= GUEST_SIZE - 32u' in generated
        assert r'event=%08x\n"' in generated
        assert 'lock_count=%08x locale_id=%08x' in generated
        assert 'suffix_dword=%08x\n"' not in generated
        assert 'lock_addr64 + 4u <= GUEST_SIZE' in generated
        assert r'locale_id=%08x\n"' in generated
        assert 'rd32(0x00a94078u)' in generated
        assert generated.count(patcher.MARKER) >= 1
        # The instrumenting script must be repeatable without double insertion.
        patcher.main()
        assert table.read_text() == generated
    finally:
        patcher.TABLE = old_table


def test_cached_dispatch_trace_compiles_as_c11(tmp_path):
    """Generated translation is C, not C++: catch mismatched shims early."""
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not cc:
        pytest.skip("C compiler unavailable")
    table = tmp_path / "table.c"
    table.write_text(
        "#include <stdint.h>\n#include <stdio.h>\n"
        "typedef struct X86 { uint32_t r[8]; } X86;\n"
        "enum { R_EAX, R_ECX, R_EDX, R_EBX, R_ESP, R_EBP, R_ESI, R_EDI };\n"
        "#define GUEST_SIZE (0x20000000u)\n"
        "static uint32_t rd32(uint32_t p) { (void)p; return 0; }\n"
        "void recomp_call(X86 *c, uint32_t target)\n{\n"
        "  (void)c; (void)target;\n}\n"
    )
    saved = patcher.TABLE
    try:
        patcher.TABLE = table
        patcher.main()
        subprocess.run(
            [cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-fsyntax-only", str(table)],
            capture_output=True, text=True, check=True,
        )
    finally:
        patcher.TABLE = saved
