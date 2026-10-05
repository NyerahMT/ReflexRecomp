#!/usr/bin/env python3
"""Build MX vs. ATV Reflex through recomp-kit."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
if not (KIT / "tools/build.py").is_file():
    sys.exit("kit/ is missing; CI clones the pinned recomp-kit automatically")
sys.exit(subprocess.call([
    sys.executable, str(KIT / "tools/build.py"), "--game-dir", str(ROOT), *sys.argv[1:]
], cwd=ROOT))
