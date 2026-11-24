"""Hiring-feed pipeline: scrape -> classify -> extract contacts -> store.

Pure logic over a `PostSource` (anything with iter_posts(keyword)), so it is
testable without a browser. Mirrors the posts pipeline but uses FeedSettings.

AI extraction: when `ai_extractor` is given (built from a configured LLM in the
stage), company/requirements/emails are refined with the LLM; regex results are
used whenever AI is unavailable. Everything stays in the SQLite repo (memory).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator
from typing import Optional
from typing import Protocol

from ...domain.models import Post
from ...extraction.contacts import AIPostExtractor
from ...extraction.contacts import analyze_post
from ...settings import FeedSettings
from ...storage.db import Repository

log = logging.getLogger(__name__)


class PostSource(Protocol):
    def iter_posts(self, keyword: str = "feed") -> Iterator[Post]: ...


@dataclass
class FeedSummary:
    scanned: int = 0
    hiring: int = 0
    new_contacts: int = 0
    duplicates: int = 0


def run_feed(
    repo: Repository,
    source: PostSource,
    cfg: FeedSettings,
    ai_extractor: Optional[AIPostExtractor] = None,
) -> FeedSummary:
    out = FeedSummary()
    for post in source.iter_posts("feed"):
        if repo.post_known(post.post_id):
            out.duplicates += 1
            continue
        out.scanned += 1
        a = analyze_post(post.text, post.hrefs, cfg.min_hiring_score, ai_extractor=ai_extractor)
        repo.add_post(
            post.post_id,
            post.url,
            post.author,
            post.text,
            post.posted_text,
            "feed",
            a.is_hiring,
            a.hiring_score,
            a.roles,
            company=a.company,
            requirements=a.requirements,
        )
        if not a.is_hiring:
            continue
        out.hiring += 1
        for c in a.contacts(post.text):
            out.new_contacts += repo.add_contact(
                c.kind, c.value, "feed", post.post_id, c.context
            )
    return out
