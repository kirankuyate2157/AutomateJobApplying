"""Rate how well a job fits the profile (0-100) or reject it outright.

WHY scoring: "apply to everything in the filters" (legacy behaviour) burns the
daily quota on poor fits. With a 30/day budget we spend it on the best 30.

Score = title match (30) + skill overlap (35) + experience fit (15)
        + freshness (15) + easy-apply bonus (5)

SUGGESTION: log score vs. recruiter response later and fit these weights from
real outcomes (a tiny logistic regression is plenty).
"""
from __future__ import annotations

import re
from datetime import datetime

from ..domain.models import Job, JobScore
from ..extraction.skills import extract_skills, required_years
from ..profile.profile import Profile

_REMOTE = re.compile(r"remote|anywhere|work from home|wfh", re.I)
_CLEARANCE = re.compile(r"security clearance|polygraph|ts/sci|\bsecret clearance\b", re.I)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def _word_present(word: str, text: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(word.lower())}(?![\w])", text.lower()) is not None


class JobScorer:
    def __init__(self, profile: Profile, now: datetime | None = None):
        self.p = profile
        self._now = now

    def score(self, job: Job) -> JobScore:
        reject = self._hard_reject(job)
        required = sorted(extract_skills(f"{job.title}\n{job.description}"))
        matched = sorted(s for s in required if s in self.p.skills)
        if reject:
            return JobScore(0, [reject], reject, matched, required)

        reasons: list[str] = []
        title_pts = self._title_points(job.title)
        reasons.append(f"title {title_pts:.0f}/30")

        if required:
            denom = min(len(required), 8)          # long wish-lists must not drown the score
            skill_pts = 35 * min(1.0, len(matched) / denom)
        else:
            skill_pts = 15                          # description gave no signal: neutral
        reasons.append(f"skills {len(matched)}/{len(required)} -> {skill_pts:.0f}/35")

        exp_pts = self._experience_points(job)
        reasons.append(f"experience {exp_pts:.0f}/15")

        fresh_pts = self._freshness_points(job)
        reasons.append(f"freshness {fresh_pts:.0f}/15")

        easy_pts = 5 if job.easy_apply else 0
        total = title_pts + skill_pts + exp_pts + fresh_pts + easy_pts
        return JobScore(round(total, 1), reasons, None, matched, required)

    # ------------------------------------------------------------ internals
    def _hard_reject(self, job: Job) -> str | None:
        text = f"{job.title}\n{job.description}"
        if job.company and job.company.lower() in {c.lower() for c in self.p.avoid_companies}:
            return f"blacklisted company: {job.company}"
        for word in self.p.avoid_keywords:
            if _word_present(word, text):
                return f"contains avoided keyword: {word}"
        if _CLEARANCE.search(text):
            return "requires security clearance"
        lo, _hi = required_years(job.description)
        if lo is not None and self.p.max_required_years and lo > self.p.max_required_years:
            return f"requires {lo:g}+ years (limit {self.p.max_required_years:g})"
        # WHY a country gate: sponsorship/authorization questions would be
        # answered "No" for jobs abroad, wasting a quota slot on a sure rejection.
        loc = job.location or ""
        if loc and not _REMOTE.search(loc) and not any(
                c.lower() in loc.lower() for c in self.p.authorized_countries):
            return f"location outside authorised countries: {loc}"
        return None

    def _title_points(self, title: str) -> float:
        title_tokens = _tokens(title)
        best = 0.0
        for role in self.p.target_roles:
            role_tokens = _tokens(role)
            if role_tokens:
                best = max(best, len(role_tokens & title_tokens) / len(role_tokens))
        return 30 * best

    def _experience_points(self, job: Job) -> float:
        lo, _ = required_years(job.description)
        if lo is None:
            return 8                                # unknown requirement: neutral
        if lo <= self.p.total_years:
            return 15
        return 15 * max(0.0, 1 - (lo - self.p.total_years) / max(1.0, self.p.max_required_years - self.p.total_years + 1))

    def _freshness_points(self, job: Job) -> float:
        if job.posted_at is None:
            return 6
        age_h = ((self._now or datetime.now()) - job.posted_at).total_seconds() / 3600
        for limit_h, pts in ((1, 15), (6, 12), (24, 9), (72, 5), (168, 2)):
            if age_h <= limit_h:
                return pts
        return 0
