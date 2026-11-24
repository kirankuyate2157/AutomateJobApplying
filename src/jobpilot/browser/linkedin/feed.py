"""LinkedIn main FEED scraping: find hiring POSTS in your feed and read their
full text.

Recruiters often skip the jobs board and post "send your CV to x@y.com" in the
feed. This scraper opens https://www.linkedin.com/feed/, scrolls the infinite
feed, expands every "...more", and returns raw Post objects (text + every href
inside the post, including mailto: links that the visible text may truncate).

Two pass modes:
  * feed pass (default) - read each post card inline while scrolling the feed.
    Fast, one page load.
  * deep pass (`feed.analyze_each_page = true`) - for every hiring post, open
    the post's own URL and re-read the full page body + comments. Comments
    often carry the real "send CV to..." address the post body truncates.

Analysis (is it a hiring post? which emails/phones/forms?) is NOT done here;
see extraction/contacts.py. Scraping and understanding stay separate.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from typing import Iterator

from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from ...core.context import AppContext
from ...domain.models import Post
from ..helpers import find_all
from ..helpers import find_first
from ..helpers import js_click
from ..helpers import pause
from ..helpers import scroll_into_view
from ..helpers import text_of
from . import selectors as S
from .session import guard

log = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"


def _click_seemore_safely(driver: Any, element: Any) -> None:
    """Click a "...more" toggle, swallowing transient Selenium errors."""
    try:
        js_click(driver, element)
        pause(0.2, 0.5)
    except (StaleElementReferenceException, WebDriverException):
        pass


class LinkedInFeedSource:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver

    def _scroll_feed(self, d: Any) -> None:
        """Scroll LinkedIn's feed container down so lazy-loaded posts render."""
        container = None
        try:
            container = d.execute_script(
                "return document.querySelector('div[class*=\"scaffold-finite-scroll__scroll-container\"]') "
                "|| document.querySelector('div.feed-container') "
                "|| document.querySelector('div[role=\"feed\"]') "
                "|| document.scrollingElement;")
        except WebDriverException:
            container = None
        if container is not None:
            try:
                d.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
            except WebDriverException:
                pass
            else:
                return
        # Fallback: scroll the window by one viewport
        d.execute_script("window.scrollBy(0, window.innerHeight);")

    def iter_posts(self, _keyword: str = "feed") -> Iterator[Post]:
        """Yield posts from the LinkedIn feed, optionally deep-analysing each.

        Scrolls the feed until either `max_posts` posts are collected or
        several consecutive scrolls surface no new posts.
        """
        d, cfg = self.driver, self.ctx.settings.feed
        d.get(FEED_URL)
        pause(2.0, 3.5)
        guard(d)
        seen: set[str] = set()
        stale_rounds = 0
        for scroll_no in range(1, cfg.max_scrolls + 1):
            new_in_round = 0
            containers = find_all(d, S.FEED_CONTAINERS)
            log.debug("scroll %d: found %d feed post containers", scroll_no, len(containers))
            for container in containers:
                try:
                    post = self._read_post(container, "feed")
                except (StaleElementReferenceException, WebDriverException):
                    continue
                if not post or post.post_id in seen:
                    continue
                seen.add(post.post_id)
                new_in_round += 1
                # Deep pass: open the post's own page for full text + comments.
                if cfg.analyze_each_page and post.url:
                    try:
                        deep = self.read_post_page(post.url)
                        if deep.text:
                            post.text = deep.text
                        post.hrefs = list(dict.fromkeys(post.hrefs + deep.hrefs))
                    except Exception:  # one bad page must not kill the run
                        log.debug("deep page read failed for %s", post.url)
                yield post
                if len(seen) >= cfg.max_posts:
                    return
            log.debug("scroll %d: %d new posts (total %d)", scroll_no, new_in_round, len(seen))
            stale_rounds = stale_rounds + 1 if new_in_round == 0 else 0
            if stale_rounds >= 4:
                log.info("no new posts after %d scrolls; ending feed", scroll_no)
                return
            self._scroll_feed(d)
            pause(1.5, 2.8)  # let lazy-loaded posts render

    def _read_post(self, container: Any, keyword: str) -> Post | None:
        d = self.driver
        scroll_into_view(d, container)
        for more in find_all(container, S.FEED_SEE_MORE)[:1]:  # expand truncated text
            _click_seemore_safely(d, more)
        text_el = find_first(container, S.FEED_TEXT)
        text = text_of(text_el) if text_el is not None else text_of(container)
        if len(text) < 30:
            return None
        hrefs = [a.get_attribute("href") or "" for a in container.find_elements(*S.FeedLinks[0])]
        hrefs = [h for h in hrefs if h.startswith(("mailto:", "http"))]
        urn = container.get_attribute("data-urn") or ""
        url = f"https://www.linkedin.com/feed/update/{urn}" if urn.startswith("urn:li:") else ""
        # stable id: the activity URN if present, else a hash of the text
        post_id = (
            re.sub(r"\W+", "_", urn) if urn else hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        )
        author_el = find_first(container, S.FEED_AUTHOR)
        time_el = find_first(container, S.FEED_TIME)
        return Post(
            post_id=post_id,
            url=url,
            author=text_of(author_el) if author_el is not None else "",
            text=text,
            posted_text=text_of(time_el).split("•")[0].strip() if time_el is not None else "",
            query=keyword,
            hrefs=hrefs,
        )

    # ------------------------------------------------------------------ deep page
    def read_post_page(self, url: str) -> Post:
        """Open a single post URL and return its full text + every href.

        Used for the deep per-page analysis pass. Returns a Post with only
        text/hrefs populated (author/id left blank - caller keeps the original).
        """
        d = self.driver
        d.get(url)
        pause(2.0, 3.5)
        guard(d)
        # expand any truncated text on the post page
        for more in find_all(d, S.FEED_SEE_MORE)[:3]:
            _click_seemore_safely(d, more)
        text_parts: list[str] = []
        for sel in S.POST_PAGE_TEXT:
            for el in find_all(d, [sel]):
                t = text_of(el)
                if t:
                    text_parts.append(t)
        # comments often carry the real apply address
        for item in find_all(d, S.POST_COMMENT_ITEM):
            for sel in S.POST_COMMENT_TEXT:
                el = find_first(item, [sel])
                if el:
                    t = text_of(el)
                    if t:
                        text_parts.append(t)
        text = "\n".join(dict.fromkeys(p for p in text_parts if p))
        hrefs: list[str] = []
        for a in d.find_elements(By.TAG_NAME, "a"):
            try:
                h = a.get_attribute("href") or ""
            except (StaleElementReferenceException, WebDriverException):
                continue
            if h.startswith(("mailto:", "http")):
                hrefs.append(h)
        hrefs = [h for h in hrefs if "linkedin.com/in/" not in h]
        return Post(post_id="", url=url, text=text, hrefs=hrefs)
