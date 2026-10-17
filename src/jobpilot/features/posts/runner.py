"""Hiring-post pipeline: scrape -> classify -> extract contacts -> store.

Pure logic over a `PostSource` (anything with iter_posts(keyword)), so it is
testable without a browser.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, Protocol

from ...domain.models import Post
from ...extraction.contacts import analyze_post
from ...settings import PostSettings
from ...storage.db import Repository

log = logging.getLogger(__name__)


class PostSource(Protocol):
    def iter_posts(self, keyword: str) -> Iterator[Post]: ...


@dataclass
class PostSummary:
    scanned: int = 0
    hiring: int = 0
    new_contacts: int = 0
    duplicates: int = 0


def run_posts(repo: Repository, source: PostSource, cfg: PostSettings) -> PostSummary:
    out = PostSummary()
    for keyword in cfg.keywords:
        log.info("scanning posts for %r", keyword)
        for post in source.iter_posts(keyword):
            if repo.post_known(post.post_id):
                out.duplicates += 1
                continue
            out.scanned += 1
            a = analyze_post(post.text, post.hrefs, cfg.min_hiring_score)
            repo.add_post(post.post_id, post.url, post.author, post.text, post.posted_text,
                          keyword, a.is_hiring, a.hiring_score, a.roles)
            if not a.is_hiring:
                continue
            out.hiring += 1
            for c in a.contacts(post.text):
                out.new_contacts += repo.add_contact(c.kind, c.value, "post", post.post_id, c.context)
    return out
