"""Master profile: the ONE place your personal facts live.

WHY: the legacy project repeated the same facts across personals.py,
questions.py, search.py, the mail template and the resume (and they drifted:
experience was 3 in one file, 4 in another). Everything now derives from
config/profile.yaml: form answers, LLM context, email templates, job scoring.

SUGGESTION: add a `jobpilot profile import-resume resume.pdf` command that
pre-fills this file using the LLM, then you only review it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..exceptions import ConfigError


@dataclass
class ResumeVariant:
    path: str
    label: str
    focus_skills: list[str] = field(default_factory=list)  # canonical skill names this resume emphasises
    default: bool = False


@dataclass
class Profile:
    # identity
    first_name: str
    last_name: str
    email: str
    phone: str
    middle_name: str = ""
    phone_country: str = "India"
    phone_code: str = "+91"
    city: str = ""
    state: str = ""
    country: str = "India"
    zip_code: str = ""
    street: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    # work
    total_years: float = 0
    current_company: str = ""
    current_title: str = ""
    notice_period_days: int = 30
    current_ctc: int = 0          # INR per annum
    expected_ctc: int = 0         # INR per annum
    headline: str = ""
    summary: str = ""
    cover_letter: str = ""
    self_rating: str = "8"        # answer for "rate yourself 1-10" style questions
    skills: dict[str, float] = field(default_factory=dict)   # canonical skill -> years
    projects: list[str] = field(default_factory=list)
    # targeting
    target_roles: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    avoid_companies: list[str] = field(default_factory=list)
    max_required_years: float = 0   # skip jobs whose headline experience requirement exceeds this
    authorized_countries: list[str] = field(default_factory=lambda: ["India"])
    requires_sponsorship: bool = False
    willing_to_relocate: bool = True
    work_modes: list[str] = field(default_factory=lambda: ["onsite", "hybrid", "remote"])
    degrees: list[str] = field(default_factory=list)          # e.g. ["bachelor"]
    demographics: dict[str, str] = field(default_factory=dict)
    canned_answers: list[dict[str, str]] = field(default_factory=list)  # [{match: regex, answer: text}]
    resumes: list[ResumeVariant] = field(default_factory=list)

    # ------------------------------------------------------------------ api
    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)

    @property
    def primary_role(self) -> str:
        return self.target_roles[0] if self.target_roles else "Software Engineer"

    def skill_years(self, canonical: str) -> float | None:
        """Years of experience with a canonical skill, None if not in the profile."""
        return self.skills.get(canonical.lower())

    def llm_context(self) -> str:
        """Compact factual summary given to the LLM. It may only use facts from here."""
        skills = ", ".join(f"{k} ({v:g}y)" for k, v in sorted(self.skills.items(), key=lambda kv: -kv[1]))
        return "\n".join([
            f"Name: {self.full_name}", f"Location: {self.city}, {self.state}, {self.country}",
            f"Total experience: {self.total_years:g} years",
            f"Current: {self.current_title} at {self.current_company}",
            f"Notice period: {self.notice_period_days} days",
            f"Current CTC (INR/yr): {self.current_ctc}; Expected CTC (INR/yr): {self.expected_ctc}",
            f"Education: {', '.join(self.degrees) or 'n/a'}",
            f"Needs visa sponsorship: {'yes' if self.requires_sponsorship else 'no'}; "
            f"authorised to work in: {', '.join(self.authorized_countries)}",
            f"Skills: {skills}", f"Summary: {self.summary.strip()}",
            "Projects: " + "; ".join(self.projects)])

    # ----------------------------------------------------------------- load
    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"{path} not found. Run `jobpilot init`, then edit it.")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Profile":
        raw = dict(raw)
        resumes = [ResumeVariant(**r) for r in raw.pop("resumes", []) or []]
        skills = {str(k).lower(): float(v) for k, v in (raw.pop("skills", {}) or {}).items()}
        known = set(cls.__dataclass_fields__)
        unknown = set(raw) - known
        if unknown:
            raise ConfigError(f"Unknown profile key(s): {sorted(unknown)}")
        missing = [k for k in ("first_name", "last_name", "email", "phone") if not raw.get(k)]
        if missing:
            raise ConfigError(f"Profile is missing required field(s): {missing}")
        raw["phone"] = str(raw["phone"])
        raw["zip_code"] = str(raw.get("zip_code", ""))
        profile = cls(resumes=resumes, skills=skills, **raw)
        if sum(1 for r in resumes if r.default) > 1:
            raise ConfigError("Only one resume may be marked default: true")
        return profile
