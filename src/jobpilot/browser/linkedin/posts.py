"""LinkedIn content-search scraping: find hiring POSTS and read their full text.

Recruiters often skip the jobs board and post "send your CV to x@y.com". This
scraper scrolls the (date-sorted) post-search results, expands every "...more",
and returns raw Post objects (text + every href inside the post, including
mailto: links that the visible text can truncate).

Analysis (is it a hiring post? which emails/phones/forms?) is NOT done here;
see extraction/contacts.py. Scraping and understanding stay separate.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Iterator
from urllib.parse import quote

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from ...core.context import AppContext
from ...domain.models import Post
from ..helpers import find_all, find_first, js_click, pause, scroll_into_view, text_of
from . import selectors as S
from .session import guard

log = logging.getLogger(__name__)


def search_url(keyword: str, date_filter: str) -> str:
    # LinkedIn expects the filter values wrapped in double quotes
    return ("https://www.linkedin.com/search/results/content/?keywords=" + quote(keyword)
            + f"&datePosted=%22{date_filter}%22&sortBy=%22date_posted%22&origin=FACETED_SEARCH")


class LinkedInPostSource:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver

    def iter_posts(self, keyword: str) -> Iterator[Post]:
        d, cfg = self.driver, self.ctx.settings.posts
        d.get(search_url(keyword, cfg.date_filter))
        pause(2.0, 3.5)
        guard(d)
        seen: set[str] = set()
        stale_rounds = 0
        for _ in range(cfg.max_scrolls):
            new_in_round = 0
            for container in find_all(d, S.POST_CONTAINERS):
                try:
                    post = self._read_post(container, keyword)
                except (StaleElementReferenceException, WebDriverException):
                    continue
                if post and post.post_id not in seen:
                    seen.add(post.post_id)
                    new_in_round += 1
                    yield post
                    if len(seen) >= cfg.max_posts_per_keyword:
                        return
            stale_rounds = stale_rounds + 1 if new_in_round == 0 else 0
            if stale_rounds >= 2:                       # two empty scrolls in a row: end of results
                return
            d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            pause(1.5, 2.8)                             # let lazy-loaded posts render

    def _read_post(self, container, keyword: str) -> Post | None:
        d = self.driver
        scroll_into_view(d, container)
        for more in find_all(container, S.POST_SEE_MORE)[:1]:    # expand truncated text
            js_click(d, more)
            pause(0.2, 0.5)
        text_el = find_first(container, S.POST_TEXT)
        text = text_of(text_el) if text_el is not None else text_of(container)
        if len(text) < 30:
            return None
        hrefs = [a.get_attribute("href") or "" for a in container.find_elements(*S.PostLinks[0])]
        hrefs = [h for h in hrefs if h.startswith(("mailto:", "http"))]
        urn = container.get_attribute("data-urn") or ""
        url = f"https://www.linkedin.com/feed/update/{urn}" if urn.startswith("urn:li:") else ""
        # stable id: the activity URN if present, else a hash of the text (survives re-scrapes)
        post_id = re.sub(r"\W+", "_", urn) if urn else hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        author_el = find_first(container, S.POST_AUTHOR)
        time_el = find_first(container, S.POST_TIME)
        return Post(post_id=post_id, url=url, author=text_of(author_el) if author_el is not None else "",
                    text=text, posted_text=text_of(time_el).split("•")[0].strip() if time_el is not None else "",
                    query=keyword, hrefs=hrefs)
