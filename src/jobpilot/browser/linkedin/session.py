"""LinkedIn login/session handling.

Strategy (most robust first):
  1. the persistent Chrome profile is already logged in -> nothing to do
  2. credentials in .env -> fill the login form
  3. otherwise (captcha, 2FA, checkpoint) -> WAIT for you to finish in the
     visible browser, then continue automatically. No pyautogui pop-ups.
"""
from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from ...exceptions import ManualInterventionRequired
from ...settings import env
from ..helpers import pause

log = logging.getLogger(__name__)
FEED = "https://www.linkedin.com/feed/"
_BLOCKED_MARKERS = ("login", "authwall", "checkpoint", "challenge", "uas/")


def is_logged_in(driver) -> bool:
    url = driver.current_url
    return "linkedin.com" in url and not any(m in url for m in _BLOCKED_MARKERS)


def needs_human(driver) -> bool:
    """True on captcha / security checkpoint pages."""
    return any(m in driver.current_url for m in ("checkpoint", "challenge"))


def wait_for_human(driver, timeout_s: int, reason: str) -> None:
    log.warning("ACTION NEEDED in the browser window: %s (waiting up to %ds)", reason, timeout_s)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not needs_human(driver) and is_logged_in(driver):
            log.info("manual step completed, continuing")
            return
        time.sleep(3)
    raise ManualInterventionRequired(f"{reason}: not completed within {timeout_s}s")


def ensure_logged_in(driver, timeout_s: int = 300) -> None:
    driver.get(FEED)
    pause(1.5, 2.5)
    if is_logged_in(driver):
        return
    email, password = env("LINKEDIN_EMAIL"), env("LINKEDIN_PASSWORD")
    if email and password:
        log.info("logging in with credentials from .env")
        driver.get("https://www.linkedin.com/login")
        try:
            driver.find_element(By.ID, "username").send_keys(email)
            driver.find_element(By.ID, "password").send_keys(password)
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
        except Exception:                          # layout changed: fall back to manual login
            log.warning("could not fill the login form automatically", exc_info=True)
        pause(2.5, 4)
    if not is_logged_in(driver) or needs_human(driver):
        wait_for_human(driver, timeout_s, "log in / solve the checkpoint")


def guard(driver, timeout_s: int = 300) -> None:
    """Call between page loads: pauses for a human if a checkpoint appears."""
    if needs_human(driver) or not is_logged_in(driver):
        wait_for_human(driver, timeout_s, "LinkedIn is asking for verification")
