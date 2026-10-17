"""LinkedIn job-search scraping: search spec in, fully-loaded Job objects out.

Yields one Job at a time WHILE its details are open in the right-hand pane;
the caller (the pipeline) may call EasyApplier.apply() immediately, which acts
on that same open job. This mirrors how the legacy bot worked, but isolated
behind a clean generator interface.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterator

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By

from ...core.context import AppContext
from ...domain.models import Job
from ...extraction.timeparse import parse_relative_time
from ...search.strategy import SearchSpec, build_search_url
from ..helpers import find_all, find_first, pause, safe_click, scroll_into_view, text_of
from . import selectors as S
from .session import guard

log = logging.getLogger(__name__)


class LinkedInJobSource:
    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver

    def iter_jobs(self, spec: SearchSpec) -> Iterator[Job]:
        d, cfg = self.driver, self.ctx.settings
        for page in range(cfg.apply.max_pages_per_query):
            d.get(build_search_url(spec, cfg.search, page))
            pause(1.5, 2.5)
            guard(d)
            if find_first(d, S.JOB_CARDS, timeout=8) is None:
                log.info("no results on page %d for %r", page + 1, spec.key)
                return
            count = len(find_all(d, S.JOB_CARDS))
            for index in range(count):
                # re-find every time: LinkedIn re-renders the list and old references go stale
                cards = find_all(d, S.JOB_CARDS)
                if index >= len(cards):
                    break
                try:
                    job = self._open_card(cards[index], spec)
                except (StaleElementReferenceException, WebDriverException):
                    log.debug("card %d unreadable, skipping", index, exc_info=True)
                    continue
                if job is not None:
                    yield job

    # ------------------------------------------------------------- internals
    def _open_card(self, card, spec: SearchSpec) -> Job | None:
        d = self.driver
        job_id = card.get_attribute("data-occludable-job-id")
        if not job_id:
            return None
        scroll_into_view(d, card)
        state = find_first(card, S.CARD_STATE)
        if state is not None and text_of(state).lower() == "applied":
            return None                                       # LinkedIn already shows it as applied

        link = find_first(card, S.CARD_LINK)
        if link is None:
            return None
        title = text_of(link).split("\n")[0].strip()
        company, location, style = self._subtitle(card)
        if not safe_click(d, link):
            return None
        pause(0.8, 1.6)

        description = find_first(d, S.JOB_DESCRIPTION, timeout=5)
        top = find_first(d, S.TOP_CARD)
        posted_at, posted_text = None, ""
        if top is not None:
            ago = find_first(top, S.POSTED_TEXT)
            posted_text = text_of(ago) if ago is not None else ""
            posted_at = parse_relative_time(posted_text.replace("Reposted", ""), datetime.now())

        hr_name = hr_link = ""
        hirer = find_first(d, S.HIRER_CARD)
        if hirer is not None:
            a = find_first(hirer, [S.XP(".//a")])
            hr_link = (a.get_attribute("href") if a is not None else "") or ""
            hr_name = text_of(find_first(hirer, [S.XP(".//span")]) or hirer).split("\n")[0]

        return Job(
            job_id=job_id, title=title, company=company, location=location, work_style=style,
            description=text_of(description) if description is not None else "",
            url=f"https://www.linkedin.com/jobs/view/{job_id}", posted_at=posted_at,
            easy_apply=find_first(d, S.EASY_APPLY_BUTTON) is not None,
            hr_name=hr_name, hr_link=hr_link, query=spec.key)

    @staticmethod
    def _subtitle(card) -> tuple[str, str, str]:
        """'Company · Pune, Maharashtra, India (Hybrid)' -> (company, location, style)."""
        el = find_first(card, S.CARD_SUBTITLE)
        raw = text_of(el) if el is not None else ""
        company, _, rest = raw.partition(" · ")
        style = ""
        if rest.endswith(")") and "(" in rest:
            rest, _, style = rest[:-1].rpartition("(")
        return company.strip(), rest.strip(), style.strip()
