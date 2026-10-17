"""Plain data objects shared by every layer.

WHY: browser code, scoring, storage and the pipeline all talk through these
small dataclasses. No layer imports another layer's internals, which is what
makes each piece swappable/testable (e.g. fake JobSource in tests).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    location: str = ""
    work_style: str = ""            # On-site | Hybrid | Remote
    description: str = ""
    url: str = ""
    posted_at: datetime | None = None
    easy_apply: bool = True
    hr_name: str = ""
    hr_link: str = ""
    query: str = ""                 # which search found it (feeds yield learning)


@dataclass
class JobScore:
    total: float
    reasons: list[str] = field(default_factory=list)
    reject_reason: str | None = None     # set => hard skip regardless of total
    matched_skills: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)


@dataclass
class FormField:
    """One question in an Easy Apply step, abstracted from Selenium."""
    label: str
    kind: str                       # text | number | textarea | select | radio | checkbox
    options: list[str] = field(default_factory=list)
    required: bool = False
    current: str = ""
    handle: Any = None              # the Selenium element(s); opaque to the engine


@dataclass
class Answer:
    value: str
    source: str                     # user | canned | rule:<name> | llm | cache
    confidence: float = 1.0


@dataclass
class Post:
    post_id: str
    url: str = ""
    author: str = ""
    text: str = ""
    posted_text: str = ""           # e.g. "3h"
    query: str = ""
    hrefs: list[str] = field(default_factory=list)   # raw hrefs inside the post (mailto:, external)


@dataclass
class Contact:
    kind: str                       # email | phone | form | ats | link
    value: str
    context: str = ""               # short snippet around the match, for review


@dataclass
class ApplyResult:
    """Outcome of one application attempt (returned by any Applier)."""
    status: str                      # applied | dry_run_ok | needs_review | external | failed
    reason: str = ""
    resume: str = ""
    external_url: str = ""
    pending: list[str] = field(default_factory=list)   # unanswered required questions
