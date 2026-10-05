#!/usr/bin/env python3
"""Run recomp-kit tests with the Reflex repository available as a game target."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
if not (KIT / "tools/test.py").is_file():
    sys.exit("kit/ is missing; CI clones the pinned recomp-kit automatically")
sys.exit(subprocess.call([
    sys.executable, str(KIT / "tools/test.py"), *sys.argv[1:]
], cwd=ROOT))
