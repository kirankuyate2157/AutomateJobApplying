"""Search planning: WHAT to search, in WHICH order, with URL building.

Two ideas replace the legacy "click through the filter UI" approach:
  1. Build the LinkedIn search URL directly (keywords, location, easy apply,
     time window, sort). One page load instead of ~25 fragile button clicks.
  2. Learn which searches actually yield applications and spend the daily
     quota there first, while still exploring rarely-run queries.

CAVEAT: LinkedIn may change URL parameters. They are isolated here (and only
here) so a change is a one-file fix. See docs/OPERATIONS.md.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from urllib.parse import urlencode

from ..profile.profile import Profile
from ..settings import SearchSettings
from ..storage.db import Repository


@dataclass(frozen=True)
class SearchSpec:
    keywords: str
    location: str
    freshness_seconds: int
    pass_no: int = 1          # 1 = fresh pass, 2 = wider fallback pass

    @property
    def key(self) -> str:
        """Stable id used in search_stats."""
        return f"{self.keywords}|{self.location}|{self.freshness_seconds}"


def build_search_url(spec: SearchSpec, cfg: SearchSettings, page: int = 0) -> str:
    params: dict[str, str] = {
        "keywords": spec.keywords,
        "location": spec.location,
        "f_TPR": f"r{spec.freshness_seconds}",     # posted within N seconds
        "sortBy": cfg.sort_by,                     # DD = most recent first
    }
    if cfg.easy_apply_only:
        params["f_AL"] = "true"
    if cfg.experience_levels:
        params["f_E"] = ",".join(str(x) for x in cfg.experience_levels)
    if cfg.work_types:
        params["f_WT"] = ",".join(str(x) for x in cfg.work_types)
    if page:
        params["start"] = str(25 * page)           # LinkedIn paginates in steps of 25
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


class QueryPlanner:
    def __init__(self, profile: Profile, cfg: SearchSettings, repo: Repository,
                 rng: random.Random | None = None):
        self.profile, self.cfg, self.repo = profile, cfg, repo
        self.rng = rng or random.Random()

    def _keywords(self) -> list[str]:
        seen: dict[str, None] = {}
        for k in [*self.profile.target_roles, *self.cfg.extra_keywords]:
            seen.setdefault(k.strip())
        return [k for k in seen if k]

    def weight(self, spec: SearchSpec, stats: dict[str, tuple[int, int, int]]) -> float:
        """Smoothed apply-rate + exploration bonus (a tiny bandit).

        (applied+1)/(seen+10): searches that produced applications rise, but a
        brand-new query is not punished to zero. The 0.5/(1+runs) term makes
        rarely-run queries get retried so we keep discovering good ones.
        """
        seen, applied, runs = stats.get(spec.key, (0, 0, 0))
        return (applied + 1) / (seen + 10) + 0.5 / (1 + runs)

    def plan(self) -> list[SearchSpec]:
        stats = self.repo.search_stats()
        specs: list[SearchSpec] = []
        passes = [(1, self.cfg.freshness_seconds)]
        if self.cfg.fallback_freshness_seconds > self.cfg.freshness_seconds:
            passes.append((2, self.cfg.fallback_freshness_seconds))
        for pass_no, seconds in passes:
            batch = [SearchSpec(k, loc, seconds, pass_no)
                     for k in self._keywords() for loc in self.cfg.locations]
            # tiny jitter breaks ties and avoids a perfectly predictable (bot-like) order
            batch.sort(key=lambda s: self.weight(s, stats) + self.rng.random() * 0.01, reverse=True)
            specs.extend(batch)
        return specs
