"""Pick the best resume variant for a job.

WHY: one generic PDF under-sells you. A backend-heavy resume for Python/AWS
jobs and a full-stack one for React/Node jobs raises the match rate with no
extra effort per application.

SUGGESTION: later, generate a per-job tailored summary paragraph with the LLM
and render it into a PDF (keep this selector as the fallback).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..profile.profile import Profile, ResumeVariant

log = logging.getLogger(__name__)


def choose_resume(profile: Profile, job_skills: set[str], root: Path | None = None) -> ResumeVariant | None:
    """Return the variant with the most focus-skill overlap; ties -> default.

    Variants whose file is missing are skipped (with a warning) instead of
    crashing the run mid-application like the legacy upload step could.
    """
    candidates: list[tuple[float, ResumeVariant]] = []
    for variant in profile.resumes:
        path = Path(variant.path)
        if root is not None and not path.is_absolute():
            path = root / path
        if not path.exists():
            log.warning("resume file missing, skipping variant '%s': %s", variant.label, path)
            continue
        overlap = len({s.lower() for s in variant.focus_skills} & job_skills)
        candidates.append((overlap + (0.5 if variant.default else 0), variant))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]
