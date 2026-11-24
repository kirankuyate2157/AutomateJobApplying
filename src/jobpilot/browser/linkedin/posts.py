"""LinkedIn content-search scraping: find hiring POSTS and read their full text.

Recruiters often skip the jobs board and post "send your CV to x@y.com". This
scraper scrolls the (date-sorted) post-search results, expands every "...more",
and returns raw Post objects (text + every href inside the post, including
mailto: links that the visible text may truncate).

Algorithm (one post at a time, content-verified):
  1. Open LinkedIn content-search URL for a keyword
  2. Scroll down, wait for new posts to render
  3. For EACH post container (one by one):
       a. Click "...see more" to expand truncated text
       b. Read full text + every href
       c. Check hiring intent before yielding — non-hiring posts are skipped
       d. Only YIELD posts that pass the hiring threshold
       e. Optional deep pass: open the post's own page for full text + comments
  4. Repeat per keyword until max_posts_per_keyword collected or no new posts

Two pass modes:
  * search pass (default) - read each post card inline while scrolling the
    search results. Fast, one page load per keyword.
  * deep pass (`posts.analyze_each_page = true`) - for every hiring post,
    open the post's own URL and re-read the full page body + comments. Comments
    often carry the real "send CV to..." address the post body truncates.

Analysis (is it a hiring post? which emails/phones/forms?) is NOT done here;
see extraction/contacts.py. Scraping and understanding stay separate.

DATA INTEGRITY: SQLite uses INSERT OR IGNORE on post_id — existing posts are
never overwritten or deleted. Re-running only adds new posts.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any
from typing import Iterator
from urllib.parse import quote

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

# Minimum text length for a post to be worth reading at all
_MIN_TEXT_LEN = 30

# How long to wait (seconds) for new posts to appear after a scroll
_SCROLL_WAIT_S = 6.0
_SCROLL_POLL_S = 0.5


def search_url(keyword: str, date_filter: str) -> str:
    # LinkedIn expects the filter values wrapped in double quotes
    return (
        "https://www.linkedin.com/search/results/content/?keywords="
        + quote(keyword)
        + f"&datePosted=%22{date_filter}%22&sortBy=%22date_posted%22&origin=FACETED_SEARCH"
    )


def _click_seemore_safely(driver: Any, element: Any) -> None:
    """Click a "...more" toggle, swallowing transient Selenium errors."""
    try:
        js_click(driver, element)
        pause(0.2, 0.5)
    except (StaleElementReferenceException, WebDriverException):
        pass


def _count_containers(d: Any) -> int:
    """Return how many post containers are currently in the DOM."""
    try:
        return len(d.find_elements(*S.POST_CONTAINERS[0]))
    except WebDriverException:
        return 0


def _wait_for_new_posts(d: Any, before_count: int) -> int:
    """After scrolling, wait until new post containers appear.

    Returns the new container count. Polls for up to _SCROLL_WAIT_S.
    """
    deadline = time.monotonic() + _SCROLL_WAIT_S
    while time.monotonic() < deadline:
        try:
            count = len(d.find_elements(*S.POST_CONTAINERS[0]))
        except WebDriverException:
            count = before_count
        if count > before_count:
            return count
        time.sleep(_SCROLL_POLL_S)
    try:
        return len(d.find_elements(*S.POST_CONTAINERS[0]))
    except WebDriverException:
        return before_count


class LinkedInPostSource:
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

    def _is_hiring_signal(self, text: str) -> bool:
        """Quick check: does this post look like a hiring post?

        Used to skip non-hiring noise before doing full extraction.
        """
        if not text:
            return False
        t = text.lower()
        signals = [
            "hiring", "we're hiring", "we are hiring",
            "send your resume", "send your cv", "share your resume",
            "apply now", "apply here", "job opening", "openings",
            "vacancy", "walk-in", "walk in", "immediate joiner",
            "join our team", "join my team", "dm me", "dm us",
            "mailto:", "forms.gle", "tally.so",
            "looking for developer", "looking for engineer",
            "looking for python", "looking for java",
        ]
        return any(sig in t for sig in signals)

    def iter_posts(self, keyword: str) -> Iterator[Post]:
        """Yield hiring posts for `keyword`, one by one.

        Each post is individually content-verified: non-hiring posts are
        skipped immediately. Only posts passing the hiring signal check are
        yielded (and optionally deep-analysed).
        """
        d, cfg = self.driver, self.ctx.settings.posts
        d.get(search_url(keyword, cfg.date_filter))
        pause(2.0, 3.5)
        guard(d)
        seen: set[str] = set()
        stale_rounds = 0
        total_yielded = 0
        total_skipped = 0

        for scroll_no in range(1, cfg.max_scrolls + 1):
            before_count = _count_containers(d)
            containers = find_all(d, S.POST_CONTAINERS)
            new_in_round = 0
            yielded_in_round = 0
            skipped_in_round = 0

            log.info(
                "posts scroll %d for %r: %d containers in DOM",
                scroll_no, keyword, len(containers),
            )

            for idx, container in enumerate(containers, start=1):
                try:
                    post = self._read_post(container, keyword)
                except (StaleElementReferenceException, WebDriverException):
                    continue
                if not post:
                    continue
                if post.post_id in seen:
                    continue

                # One-by-one content check: skip non-hiring posts early
                if not self._is_hiring_signal(post.text):
                    seen.add(post.post_id)
                    skipped_in_round += 1
                    total_skipped += 1
                    log.debug(
                        "posts scroll %d for %r post %d: SKIPPED (not hiring): %s",
                        scroll_no, keyword, idx, post.text[:80].replace("\n", " | "),
                    )
                    continue

                seen.add(post.post_id)
                new_in_round += 1
                yielded_in_round += 1
                total_yielded += 1

                # Deep pass: open the post's own page for full text + comments.
                if cfg.analyze_each_page and post.url:
                    try:
                        deep = self.read_post_page(post.url)
                        if deep.text:
                            post.text = deep.text
                        post.hrefs = list(dict.fromkeys(post.hrefs + deep.hrefs))
                    except Exception:  # one bad page must not kill the run
                        log.debug("deep page read failed for %s", post.url)

                log.info(
                    "posts scroll %d for %r post %d: YIELDED (hiring) author=%s text=%s",
                    scroll_no, keyword, idx, post.author,
                    post.text[:120].replace("\n", " | "),
                )
                yield post

                if len(seen) >= cfg.max_posts_per_keyword:
                    return

            log.info(
                "posts scroll %d for %r: yielded=%d skipped=%d new=%d total_seen=%d total_yielded=%d total_skipped=%d",
                scroll_no, keyword, yielded_in_round, skipped_in_round, new_in_round,
                len(seen), total_yielded, total_skipped,
            )

            # Wait for new posts to load after this scroll round
            after_count = _wait_for_new_posts(d, before_count)
            new_loaded = after_count - before_count
            log.debug(
                "posts scroll %d for %r: DOM went %d -> %d containers (%d new)",
                scroll_no, keyword, before_count, after_count, new_loaded,
            )

            stale_rounds = stale_rounds + 1 if new_in_round == 0 else 0
            if stale_rounds >= 4:
                log.info(
                    "no new hiring posts after %d scrolls; ending %r", scroll_no, keyword
                )
                return
            self._scroll_feed(d)
            pause(1.5, 2.8)  # let lazy-loaded posts render

        log.info(
            "posts complete for %r: total_seen=%d total_yielded=%d total_skipped=%d",
            keyword, len(seen), total_yielded, total_skipped,
        )

    def _read_post(self, container: Any, keyword: str) -> Post | None:
        d = self.driver
        scroll_into_view(d, container)
        for more in find_all(container, S.POST_SEE_MORE)[:1]:  # expand truncated text
            _click_seemore_safely(d, more)
        text_el = find_first(container, S.POST_TEXT)
        text = text_of(text_el) if text_el is not None else text_of(container)
        if len(text) < _MIN_TEXT_LEN:
            return None
        hrefs = [a.get_attribute("href") or "" for a in container.find_elements(*S.PostLinks[0])]
        hrefs = [h for h in hrefs if h.startswith(("mailto:", "http"))]
        urn = container.get_attribute("data-urn") or ""
        url = f"https://www.linkedin.com/feed/update/{urn}" if urn.startswith("urn:li:") else ""
        # stable id: the activity URN if present, else a hash of the text
        post_id = (
            re.sub(r"\W+", "_", urn) if urn else hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        )
        author_el = find_first(container, S.POST_AUTHOR)
        time_el = find_first(container, S.POST_TIME)
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
        for more in find_all(d, S.POST_SEE_MORE)[:3]:
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
