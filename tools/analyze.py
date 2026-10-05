#!/usr/bin/env python3
"""Export MXReflex.exe translation inputs using Ghidra's default analyzers.

Usage:
    tools/analyze.py --ghidra-home /path/to/ghidra_12.1.3_PUBLIC

Run tools/setup.py --install /path/to/reflex --link-only first.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
GHIDRA_VERSION = "12.1.3"


def load_game_config():
    spec = importlib.util.spec_from_file_location("game_config", KIT / "tools/game_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ghidra-home", type=Path, default=os.environ.get("GHIDRA_HOME"))
    parser.add_argument("--java-home", type=Path, default=os.environ.get("JAVA_HOME"))
    parser.add_argument("--max-memory", default="12G")
    args = parser.parse_args()

    if not (KIT / "tools/ExportProgram.java").is_file():
        sys.exit("kit/ is missing or does not contain ExportProgram.java")
    if not args.ghidra_home:
        sys.exit(f"Set --ghidra-home or GHIDRA_HOME to Ghidra {GHIDRA_VERSION}")

    ghidra = args.ghidra_home.expanduser().resolve()
    properties = ghidra / "Ghidra/application.properties"
    if not properties.is_file() or f"application.version={GHIDRA_VERSION}\n" not in properties.read_text():
        sys.exit(f"Use Ghidra {GHIDRA_VERSION}; got {ghidra}")

    cfg = load_game_config().load(ROOT)
    exe = cfg["developer_exe_path"]
    if not exe.is_file():
        sys.exit(f"{exe} is missing; run tools/setup.py --install ... --link-only first")

    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    expected = cfg["game"]["sha256"]
    if digest != expected:
        sys.exit(f"Unsupported {exe.name}: SHA-256 {digest}; expected {expected}")

    env = dict(os.environ)
    if args.java_home:
        env["JAVA_HOME"] = str(args.java_home.expanduser().resolve())
        env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env.get("PATH", "")
    env["MAXMEM"] = args.max_memory

    listings = cfg["listings_path"]
    output = listings.parent
    project = output.parent / "ghidra"
    project.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    command = [
        str(ghidra / "support/analyzeHeadless"),
        str(project),
        cfg["game"]["app_name"],
        "-import", str(exe),
        "-deleteProject",
        "-scriptPath", str(KIT / "tools"),
        "-postScript", "ExportProgram.java", str(output),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)

    index = listings / "functions.tsv"
    if not index.is_file() or len(index.read_text().splitlines()) < 2:
        sys.exit("Ghidra did not export a function index; inspect the workflow log")

    (output / "inputs.json").write_text(json.dumps({
        "executable_sha256": expected,
        "annotations_revision": None,
        "ghidra_analysis": "default analyzers",
        "ghidra_version": GHIDRA_VERSION,
    }, indent=2) + "\n")

    print(f"Listings ready in {listings}")
    print("Next: tools/build.py --target gen --regenerate")


if __name__ == "__main__":
    main()
