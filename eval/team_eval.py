"""Run the weekly team feature suite, including planted time series and event warnings.

The former supervisor-chat evaluation and its CLI are reproducible at commit 224ba1e.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="the weekly suite always runs offline")
    parser.parse_args()
    backend = Path(__file__).resolve().parents[1] / "backend"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_team_briefing.py"],
        cwd=backend,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
