"""Offline SteamUser ABI regression: nullptr result with explicit cdecl."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_steam_user_is_known_cdecl_and_null_without_session():
    source = (ROOT / "runtime" / "reflex_compat.cpp").read_text()
    decl = '{"steam_api.dll", "SteamUser", ARGC_CDECL, reflex_steam_user}'
    assert source.count(decl) == 1
    function = source.index("void reflex_steam_user(X86 *c) {")
    body = source[function:source.index("\n}\n", function) + 2]
    assert "set_eax(c, 0);" in body
    assert "reflex_steam_init(X86 *c)" in source
    assert "reflex_steam_run_callbacks(X86 *c)" in source
    assert "reflex_steam_shutdown(X86 *c)" in source
