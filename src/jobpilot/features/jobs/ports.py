"""Ports (interfaces) the jobs pipeline depends on.

WHY: the pipeline knows nothing about Selenium or LinkedIn. Any object with
these methods works: the LinkedIn adapters in production, tiny fakes in tests,
and later a NaukriSource / IndeedSource / WellfoundSource for new job boards.
"""
from __future__ import annotations

from typing import Iterator, Protocol

from ...domain.models import ApplyResult, Job
from ...search.strategy import SearchSpec


class JobSource(Protocol):
    def iter_jobs(self, spec: SearchSpec) -> Iterator[Job]: ...


class Applier(Protocol):
    def apply(self, job: Job, resume_path: str = "") -> ApplyResult: ...
