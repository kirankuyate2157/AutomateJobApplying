"""LinkedIn content-search scraping: find hiring POSTS and read their full text.

Recruiters often skip the jobs board and post "send your CV to x@y.com". This
scraper scrolls the (date-sorted) post-search results, expands every "...more",
and returns raw Post objects (text + every href inside the post, including
mailto: links that the visible text may truncate).

Two pass modes:
  * search pass (default) - read each post card inline while scrolling the
    search results. Fast, one page load per keyword.
  * deep pass (`posts.analyze_each_page = true`) - for every hiring post,
    open the post's own URL and re-read the full page body + comments. Comments
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


def search_url(keyword: str, date_filter: str) -> str:
    # LinkedIn expects the filter values wrapped in double quotes
    return (
        "https://www.linkedin.com/search/results/content/?keywords="
        + quote(keyword)
        + f"&datePosted=%22{date_filter}%22&sortBy=%22date_posted%22&origin=FACETED_SEARCH"
    )


def _click_seemore_safely(driver: Any, element: Any) -> None:
    """Click a "...more" toggle, swallowing transient Selenium errors.

    Keeping the try/except out of the caller's loop avoids PERF203 while still
    being defensive about stale elements.
    """
    try:
        js_click(driver, element)
        pause(0.2, 0.5)
    except (StaleElementReferenceException, WebDriverException):
        pass


class LinkedInPostSource:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver

    def _scroll_feed(self, d: Any) -> None:
        """Scroll LinkedIn's feed container down so lazy-loaded posts render.

        Tries the feed scroll container first, then falls back to scrolling the
        window by one viewport. LinkedIn search results paginate via "Load more"
        rather than infinite scroll, so callers should also click that button.
        """
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
        # Fallback: scroll the window by one viewport (gentler than jump-to-bottom)
        d.execute_script("window.scrollBy(0, window.innerHeight);")

    def iter_posts(self, keyword: str) -> Iterator[Post]:
        """Yield posts for `keyword`, optionally deep-analysing each one's page.

        Scrolls LinkedIn's feed container until either `max_posts_per_keyword`
        posts are collected or several consecutive scrolls surface no new posts.
        """
        d, cfg = self.driver, self.ctx.settings.posts
        d.get(search_url(keyword, cfg.date_filter))
        pause(2.0, 3.5)
        guard(d)
        seen: set[str] = set()
        stale_rounds = 0
        for scroll_no in range(1, cfg.max_scrolls + 1):
            new_in_round = 0
            containers = find_all(d, S.POST_CONTAINERS)
            log.debug("scroll %d: found %d post containers", scroll_no, len(containers))
            for container in containers:
                try:
                    post = self._read_post(container, keyword)
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
                if len(seen) >= cfg.max_posts_per_keyword:
                    return
            log.debug("scroll %d: %d new posts (total %d)", scroll_no, new_in_round, len(seen))
            if new_in_round == 0:
                # LinkedIn content search paginates via "Load more": try clicking it,
                # then re-scan before counting this round as stale.
                load_more = find_first(d, S.LOAD_MORE_BUTTON)
                if load_more is not None:
                    _click_seemore_safely(d, load_more)
                    log.debug("clicked 'Load more' button for %r", keyword)
                    pause(2.0, 3.0)
                    containers2 = find_all(d, S.POST_CONTAINERS)
                    new_in_round2 = 0
                    for container in containers2:
                        try:
                            post = self._read_post(container, keyword)
                        except (StaleElementReferenceException, WebDriverException):
                            continue
                        if not post or post.post_id in seen:
                            continue
                        seen.add(post.post_id)
                        new_in_round2 += 1
                        if cfg.analyze_each_page and post.url:
                            try:
                                deep = self.read_post_page(post.url)
                                if deep.text:
                                    post.text = deep.text
                                post.hrefs = list(dict.fromkeys(post.hrefs + deep.hrefs))
                            except Exception:
                                log.debug("deep page read failed for %s", post.url)
                        yield post
                        if len(seen) >= cfg.max_posts_per_keyword:
                            return
                    log.debug("after load-more: %d new posts (total %d)", new_in_round2, len(seen))
                    new_in_round = new_in_round2
                else:
                    log.debug("no 'Load more' button found for %r", keyword)
            stale_rounds = stale_rounds + 1 if new_in_round == 0 else 0
            if stale_rounds >= 4:
                log.info("no new posts after %d scrolls; ending %r", scroll_no, keyword)
                return
            self._scroll_feed(d)
            pause(1.5, 2.8)  # let lazy-loaded posts render

    def _read_post(self, container: Any, keyword: str) -> Post | None:
        d = self.driver
        scroll_into_view(d, container)
        for more in find_all(container, S.POST_SEE_MORE)[:1]:  # expand truncated text
            _click_seemore_safely(d, more)
        text_el = find_first(container, S.POST_TEXT)
        text = text_of(text_el) if text_el is not None else text_of(container)
        if len(text) < 30:
            return None
        hrefs = [a.get_attribute("href") or "" for a in container.find_elements(*S.PostLinks[0])]
        hrefs = [h for h in hrefs if h.startswith(("mailto:", "http"))]
        urn = container.get_attribute("data-urn") or ""
        url = f"https://www.linkedin.com/feed/update/{urn}" if urn.startswith("urn:li:") else ""
        # stable id: the activity URN if present, else a hash of the text (survives re-scrapes)
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
