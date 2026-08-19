#!/usr/bin/env python3
"""ONE-COMMAND test runner for JARVIS.

Runs, in order:
  1. The consolidated pytest suite (tests/test_*.py, excluding legacy/).
  2. Every legacy standalone suite in tests/legacy/.

Usage:
    .venv/bin/python run_tests.py            # everything
    .venv/bin/python run_tests.py --fast     # pytest only
Exits non-zero if anything fails.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / ".venv" / "bin" / "python") or sys.executable
LEGACY_DIR = ROOT / "tests" / "legacy"

FAST = "--fast" in sys.argv


def run(cmd: list[str], cwd: Path | None = None) -> int:
    print("\n$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(cwd or ROOT))


def main() -> int:
    failures: list[str] = []

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    rc = run([PY, "-m", "pytest", "tests/", "-q",
              "--ignore=tests/legacy"])
    if rc != 0:
        failures.append("pytest (consolidated)")
    if FAST:
        return 1 if failures else 0

    for script in sorted(LEGACY_DIR.glob("test_*.py")):
        rc = subprocess.call([PY, str(script)], cwd=str(ROOT), env=env)
        if rc != 0:
            failures.append(script.name)

    print("\n" + "=" * 60)
    if failures:
        print("FAILED SUITES:")
        for name in failures:
            print("  -", name)
        return 1
    print("ALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
