#!/usr/bin/env python3
"""Patch scalar/packed SSE forms Reflex reaches in the pinned translator."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATOR = ROOT / "kit" / "tools" / "recomp" / "translate.py"


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if marker in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"translator patch anchor for {marker!r} was not unique")
    return text.replace(old, new, 1)


def main() -> None:
    if not TRANSLATOR.is_file():
        raise SystemExit(f"missing pinned translator: {TRANSLATOR}")

    text = TRANSLATOR.read_text()
    text = replace_once(
        text,
        '            single = m.endswith("SS") and m not in ("CVTSD2SS",)\n',
        '            single = ((m.endswith("SS") and m not in ("CVTSD2SS",))\n'
        '                      or m == "CVTTSS2SI")\n',
        'or m == "CVTTSS2SI"',
    )

    text = replace_once(
        text,
        'SSE_LANE_FORMS = ("PANDN", "ANDNPD", "ANDNPS", "PCMPEQD", "PUNPCKLDQ", "PUNPCKHDQ",\n'
        '                          "PUNPCKLQDQ", "UNPCKLPD", "UNPCKHPD", "MOVDDUP", "MOVLPD", "MOVLPS",',
        'SSE_LANE_FORMS = ("PANDN", "ANDNPD", "ANDNPS", "PCMPEQD", "PUNPCKLDQ", "PUNPCKHDQ",\n'
        '                          "UNPCKLPS", "UNPCKHPS", "PUNPCKLQDQ", "UNPCKLPD", "UNPCKHPD",\n'
        '                          "MOVDDUP", "MOVLPD", "MOVLPS",',
        '"UNPCKLPS", "UNPCKHPS"',
    )
    text = replace_once(
        text,
        '            elif m == "PUNPCKLDQ":            # d0 s0 d1 s1\n',
        '            elif m in ("PUNPCKLDQ", "UNPCKLPS"):  # d0 s0 d1 s1\n',
        '("PUNPCKLDQ", "UNPCKLPS")',
    )
    text = replace_once(
        text,
        '            elif m == "PUNPCKHDQ":            # d2 s2 d3 s3\n',
        '            elif m in ("PUNPCKHDQ", "UNPCKHPS"):  # d2 s2 d3 s3\n',
        '("PUNPCKHDQ", "UNPCKHPS")',
    )
    TRANSLATOR.write_text(text)
    print("Applied packed-single SSE unpack support to pinned translator")


if __name__ == "__main__":
    main()
