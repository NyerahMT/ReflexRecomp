#!/usr/bin/env python3
"""Inject Reflex-only runtime compatibility into the pinned recomp-kit checkout."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
SOURCE = ROOT / "runtime" / "reflex_compat.cpp"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    if not (KIT / "runtime" / "CMakeLists.txt").is_file():
        raise SystemExit("kit/ is missing the pinned recomp-kit runtime")
    if not SOURCE.is_file():
        raise SystemExit(f"missing {SOURCE}")

    target = KIT / "runtime" / "reflex_compat.cpp"
    shutil.copyfile(SOURCE, target)

    cmake = KIT / "runtime" / "CMakeLists.txt"
    replace_once(
        cmake,
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp)",
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp reflex_compat.cpp)",
        "reflex_compat.cpp)",
    )

    imports = KIT / "runtime" / "imports.cpp"
    replace_once(
        imports,
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "}",
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "    extern void reflex_compat_register();\n"
        "    reflex_compat_register();\n"
        "}",
        "reflex_compat_register();",
    )

    print("Applied Reflex runtime import/ABI compatibility patch")


if __name__ == "__main__":
    main()
