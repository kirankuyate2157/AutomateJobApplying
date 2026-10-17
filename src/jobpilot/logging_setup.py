"""Central logging config.

WHY: the legacy bot used print_lg() writing to one ever-growing log.txt and
popped pyautogui alerts on failure. Standard `logging` gives levels, rotation
and works unattended (cron/headless).
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    file_h = logging.handlers.RotatingFileHandler(
        log_dir / "jobpilot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)       # file keeps everything for post-mortems
    file_h.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)

    root.addHandler(file_h)
    root.addHandler(console)
    # selenium/urllib3 are very chatty at DEBUG
    for noisy in ("selenium", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
