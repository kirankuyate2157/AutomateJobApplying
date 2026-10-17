"""Small, defensive Selenium helpers shared by every LinkedIn page object.

WHY: LinkedIn's DOM is dynamic and elements go stale constantly. These helpers
return None/False instead of raising for the common transient failures, so
page objects stay readable and one flaky element never kills a whole run.
"""
from __future__ import annotations

import random
import time
from typing import Iterable, Sequence

from selenium.common.exceptions import (ElementClickInterceptedException, ElementNotInteractableException,
                                        StaleElementReferenceException, WebDriverException)
from selenium.webdriver.common.by import By

Selector = tuple[str, str]


def XP(expr: str) -> Selector:
    return (By.XPATH, expr)


def CLS(name: str) -> Selector:
    return (By.CLASS_NAME, name)


def CSS(expr: str) -> Selector:
    return (By.CSS_SELECTOR, expr)


def find_first(root, selectors: Iterable[Selector], timeout: float = 0.0):
    """First element matching ANY selector (tried in order); polls until timeout."""
    selectors = list(selectors)
    deadline = time.monotonic() + timeout
    while True:
        for by, value in selectors:
            try:
                found = root.find_elements(by, value)
                if found:
                    return found[0]
            except (WebDriverException, StaleElementReferenceException):
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def find_all(root, selectors: Iterable[Selector]) -> list:
    """All elements for the first selector that matches anything."""
    for by, value in selectors:
        try:
            found = root.find_elements(by, value)
            if found:
                return found
        except (WebDriverException, StaleElementReferenceException):
            continue
    return []


def text_of(element) -> str:
    """innerText is more reliable than .text for visually-hidden spans."""
    try:
        return (element.get_attribute("innerText") or element.text or "").strip()
    except (WebDriverException, StaleElementReferenceException):
        return ""


def js_click(driver, element) -> None:
    driver.execute_script("arguments[0].click();", element)


def safe_click(driver, element) -> bool:
    try:
        element.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException):
        try:
            js_click(driver, element)         # overlays/animations: click via JS instead
            return True
        except WebDriverException:
            return False
    except (StaleElementReferenceException, WebDriverException):
        return False


def scroll_into_view(driver, element, center: bool = True) -> None:
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: arguments[1], behavior: 'instant'});",
            element, "center" if center else "start")
    except WebDriverException:
        pass


def pause(low: float = 0.6, high: float = 1.6) -> None:
    """Randomised human-like delay (also spaces out requests politely)."""
    time.sleep(random.uniform(low, high))


def page_text_contains(driver, needle: str) -> bool:
    try:
        return needle.lower() in (driver.find_element(By.TAG_NAME, "body").get_attribute("innerText") or "").lower()
    except WebDriverException:
        return False
