"""Unit tests for the LinkedIn post scraper (deep per-page analysis).

These use a mock Selenium driver so they run without a browser, validating the
read_post_page algorithm (full text + comment hrefs) in isolation.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock

from jobpilot.browser.linkedin.posts import LinkedInPostSource
from jobpilot.browser.linkedin.posts import _click_seemore_safely


class _FakeEl:
    """Minimal fake Selenium element."""

    def __init__(self, text: str = "", href: str = "", tag_name: str = "div"):
        self._text = text
        self._href = href
        self.tag_name = tag_name

    def get_attribute(self, name: str):
        if name == "href":
            return self._href
        if name == "innerText":
            return self._text
        return None

    def find_elements(self, by, value: str):  # pragma: no cover - comments not simulated
        return []

    def text(self):  # pragma: no cover - not used by text_of (uses get_attribute)
        return self._text


class _FakeDriver:
    """Fake driver sufficient for read_post_page."""

    def __init__(self, page_html_text: str, links: list[tuple[str, str]]):
        self._text = page_html_text
        self._links = links  # list of (visible_text, href)
        self.current_url = "https://www.linkedin.com/feed/update/urn:li:activity:123"

    def get(self, url: str) -> None:  # pragma: no cover - navigation not simulated
        self.current_url = url

    def execute_script(self, script: str, *args) -> None:
        return None

    def find_elements(self, by, value: str):
        # Simulate anchor tags for href collection
        if by == "tag name" and value == "a":
            return [_FakeEl(t, h, "a") for t, h in self._links]
        # Simulate post-text containers for any other selector (CSS/XPath)
        if self._text:
            return [_FakeEl(self._text)]
        return []

    def find_element(self, by, value: str):  # pragma: no cover - not used
        return None


class _FakeCtx:
    def __init__(self, driver):
        settings = types.SimpleNamespace()
        settings.posts = types.SimpleNamespace(
            enabled=True,
            keywords=["k"],
            date_filter="past-24h",
            max_scrolls=1,
            max_posts_per_keyword=5,
            min_hiring_score=3,
            ai_extract=False,
            analyze_each_page=True,
        )
        self.settings = settings
        self.driver = driver


class ClickSeemoreSafelyTests(unittest.TestCase):
    def test_clicks_and_pauses(self):
        driver = MagicMock()
        el = MagicMock()
        _click_seemore_safely(driver, el)
        driver.execute_script.assert_called()
        # pause is called internally (real time.sleep) - just ensure no exception

    def test_swallows_stale_element(self):
        from selenium.common.exceptions import StaleElementReferenceException

        driver = MagicMock()
        driver.execute_script.side_effect = StaleElementReferenceException("gone")
        el = MagicMock()
        # should not raise
        _click_seemore_safely(driver, el)


class ReadPostPageTests(unittest.TestCase):
    def test_extracts_text_and_hrefs(self):
        text = "We are hiring a Python developer! Send CV to hr@acme.com"
        driver = _FakeDriver(
            text,
            links=[
                ("mailto", "mailto:hr@acme.com"),
                ("form", "https://forms.gle/xyz"),
                ("profile", "https://linkedin.com/in/someone"),
            ],
        )
        ctx = _FakeCtx(driver)
        source = LinkedInPostSource(ctx)  # type: ignore[arg-type]  # test mock satisfies AppContext shape
        post = source.read_post_page("https://www.linkedin.com/feed/update/urn:li:activity:123")
        self.assertIn("hiring", post.text)
        self.assertIn("mailto:hr@acme.com", post.hrefs)
        self.assertIn("https://forms.gle/xyz", post.hrefs)
        # profile links are filtered out as noise
        self.assertNotIn("linkedin.com/in/someone", post.hrefs)


if __name__ == "__main__":
    unittest.main()
