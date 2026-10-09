"""Regression test: injected trace strings must remain valid C source."""
import importlib.util
from pathlib import Path

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
        assert r'lock_count=%08x\n"' in generated
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
