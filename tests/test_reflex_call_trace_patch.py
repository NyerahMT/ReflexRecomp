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
        assert '[reflex-worker-null]' in generated
        assert '[reflex-post-loader-vcall]' in generated
        assert 'trace_ret == 0x0079a61du || trace_ret == 0x0079a627u' in generated
        assert 'trace_ret == 0x0079a63fu' in generated
        assert 'const uint32_t object = slot_ok ? rd32(slot) : 0u;' in generated
        assert 'const uint32_t release = vtable_ok ? rd32(vtable + 8u) : 0u;' in generated
        assert 'method94=%08x method9c=%08x' in generated
        assert 'owner_slot=%08x owner_slot_value=%08x' in generated
        assert 'slot_minus4=%08x' in generated
        assert 'c->r[R_ESI], c->r[R_EBP], trace_esp' in generated
        assert 'arg_ok ? rd32(trace_esp + 4u) : 0xffffffffu' in generated
        assert 'trace_ret == 0x008065b9u' in generated
        assert 'trace_ret == 0x008065b9u || trace_ret == 0x008067fdu' in generated
        assert 'trace_ret == 0x0080fc3cu' in generated
        assert 'trace_esp + 16u <= GUEST_SIZE' in generated
        assert 'p + 16u <= GUEST_SIZE' in generated
        assert 'valid ? rd32(p + 12u)' in generated
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


def test_post_intro_crash_asm_qualification_is_bounded():
    workflow = (SCRIPT.parent.parent / ".github" / "workflows" / "fast-iterate.yml").read_text()
    assert "--start 0x00806560 --end 0x008065e0" in workflow
    assert "post-intro-null-call-asm-window.txt" in workflow
    assert "--start 0x008067a0 --end 0x00806840" in workflow
    assert "fmod-next-null-call-asm-window.txt" in workflow
    assert "--start 0x0080fbe0 --end 0x0080fc70" in workflow
    assert "post-fmod-null-call-asm-window.txt" in workflow


def test_guest_stream_pointer_watch_scoped_to_extended_run_only():
    workflow = (SCRIPT.parent.parent / ".github" / "workflows" / "fast-iterate.yml").read_text()
    marker = "      - name: Qualify original MXTables loading through extended 14-minute run"
    assert workflow.count(marker) == 1
    earlier, extended = workflow.split(marker, 1)
    extended = extended.split("      # Count observed compatibility gaps", 1)[0]
    assert "RECOMP_WATCH=01ce86b4:4" not in earlier
    assert "RECOMP_WATCH=01ce86b4:4" in extended
    assert "watch: 01ce86b4 " in extended
    assert "build/logs/runtime-long-load.log" in extended
    env_lines = [line.strip() for line in extended.splitlines()]
    assert any("RECOMP_WATCH_FRAME=1" in line and
               "RECOMP_WATCH=01ce86b4:4" in env_lines[i + 1]
               for i, line in enumerate(env_lines[:-1]))


def test_post_atoi_and_seh_windows_remain_bounded_diagnostic_only():
    workflow = (SCRIPT.parent.parent / ".github" / "workflows" / "fast-iterate.yml").read_text()
    assert "--start 0x0079a5e0 --end 0x0079a660" in workflow
    assert "--start 0x00797300 --end 0x00797370" in workflow
    assert "post-atoi-null-call-asm-window.txt" in workflow
    assert "post-atoi-seh-crash-asm-window.txt" in workflow
    assert workflow.index("post-atoi-null-call-asm-window.txt") < workflow.index(
        "      - name: Audit cached translation opcode coverage")
