#!/usr/bin/env python3
"""Link and validate a user-owned Reflex installation through recomp-kit."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
if not (KIT / "tools/setup.py").is_file():
    sys.exit("kit/ is missing; CI clones the pinned recomp-kit automatically")
sys.exit(subprocess.call([
    sys.executable, str(KIT / "tools/setup.py"), "--game-dir", str(ROOT), *sys.argv[1:]
], cwd=ROOT))
