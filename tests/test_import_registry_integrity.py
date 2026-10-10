"""Static ABI integrity tests for the clean-room import registry.

These catch duplicate registrations, accidental loss of Win32 x86 argument
arity and dead handler symbols before the expensive game-core build runs.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
START = "const ImportShim k_reflex_shims[] = {"
assert START in SOURCE
TABLE = SOURCE.split(START, 1)[1].split("\n};", 1)[0]

ENTRY = re.compile(
    r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*'
    r'(ARGC_CDECL|\d+)\s*,\s*([a-zA-Z_][\w]*)\s*\}',
    re.DOTALL,
)


def records():
    return list(ENTRY.findall(TABLE))


def test_compatible_exports_are_unique_and_handled():
    entries = records()
    assert len(entries) >= 100, "import parser failed or shim table was removed"
    keys = [(dll.lower(), name.lower()) for dll, name, _argc, _fn in entries]
    assert len(keys) == len(set(keys)), "duplicate DLL/export registration"
    for dll, name, count, handler in entries:
        assert count == "ARGC_CDECL" or int(count) >= 0, (dll, name)
        assert re.search(rf"\bvoid\s+{re.escape(handler)}\(X86\s*\*c\)\s*\{{",
                         SOURCE), (dll, name, handler)


def test_crt_exports_use_cdecl_except_known_thiscall_type_info():
    thiscall = "?_name_internal_method@type_info@@QBEPBDPAU__type_info_node@@@Z"
    for dll, name, count, _handler in records():
        if dll.lower() != "msvcr90.dll":
            continue
        assert count == ("1" if name == thiscall else "ARGC_CDECL"), name


def test_msvcp90_string_assignment_copy_has_thiscall_abi():
    registry = {(dll.lower(), name): (argc, handler)
                for dll, name, argc, handler in records()}
    assert registry[("msvcp90.dll", "??4?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAEAAV01@ABV01@@Z")] == (
        "1", "msvcp_string_assign_copy"
    )


def test_xinput_ordinals_and_d3dx_signatures_are_nonvariadic_stdcall():
    registry = {(dll.lower(), name.lower()): count
                for dll, name, count, _handler in records()}
    assert registry["xinput1_3.dll", "ord2"] == "2"
    assert registry["xinput1_3.dll", "ord4"] == "3"
    assert registry["xinput1_3.dll", "ord5"] == "1"
    assert registry["d3dx9_43.dll", "d3dxgetshaderconstanttable"] == "2"
    assert registry["d3dx9_43.dll", "d3dxcompileshader"] == "10"
    assert "static_assert(sizeof(methods) / sizeof(methods[0]) == 27" in SOURCE
