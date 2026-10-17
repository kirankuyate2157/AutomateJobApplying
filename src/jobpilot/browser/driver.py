"""Chrome WebDriver factory.

WHY this is much simpler than the legacy open_chrome.py + windows-setup.bat:
Selenium >= 4.6 ships "Selenium Manager", which downloads the matching
chromedriver automatically. No manual driver installs, no PATH edits.

WHY a dedicated profile dir (data/chrome-profile): you log in to LinkedIn
once and the session persists, without touching your everyday Chrome profile
(which the legacy bot required you to close first).

Requires the optional extra:  pip install "jobpilot[browser]"
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..settings import Settings

log = logging.getLogger(__name__)


def make_driver(settings: Settings):
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:      # pragma: no cover - environment dependent
        raise RuntimeError("Selenium is not installed. Run: pip install 'jobpilot[browser]'") from exc

    cfg = settings.browser
    profile_dir = settings.path(cfg.user_data_dir)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument(f"--window-size={cfg.window_size}")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--no-first-run")
    opts.add_argument("--disable-blink-features=AutomationControlled")   # fewer automation tells
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    if cfg.headless:
        opts.add_argument("--headless=new")
    log.info("starting Chrome (profile=%s, headless=%s)", profile_dir, cfg.headless)
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(cfg.page_load_timeout_s)
    return driver
