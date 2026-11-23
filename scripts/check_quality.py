"""Run code-quality checks: ruff (lint + format) + mypy (static types).

Resolves ruff/mypy from the same environment as the running Python (e.g. the
activated venv) so it works whether or not those bins are on PATH.

Usage:
    python scripts/check_quality.py        # run everything, exit non-zero on failure
    python scripts/check_quality.py ruff   # lint only
    python scripts/check_quality.py mypy   # type-check only
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Locate ruff/mypy next to the running interpreter (venv), then fall back to PATH.
_BIN_DIR = Path(sys.executable).parent


def _exe(name: str) -> str:
    candidate = _BIN_DIR / name
    if candidate.exists():
        return str(candidate)
    return name


CHECKS = {
    "ruff": [_exe("ruff"), "check", str(SRC)],
    "ruff-format": [_exe("ruff"), "format", "--check", str(SRC)],
    "mypy": [_exe("mypy"), str(SRC)],
}


def run(name: str, cmd: list[str]) -> int:
    print(f"==> {name}: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"   FAILED ({name}) exit={result.returncode}")
    else:
        print(f"   OK ({name})")
    return result.returncode


def main() -> int:
    args = sys.argv[1:]
    to_run = args if args else list(CHECKS)
    codes: list[int] = []
    for name in to_run:
        key = name if name in CHECKS else None
        if key is None:
            print(f"unknown check: {name}. Available: {', '.join(CHECKS)}")
            return 2
        codes.append(run(key, CHECKS[key]))
    return 1 if any(c != 0 for c in codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
