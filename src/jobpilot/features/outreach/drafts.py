"""Turn harvested email contacts into reviewed-or-auto-sent application drafts.

WHY a separate step (not "send as soon as an email is found"): relevance is
checked first (only hiring posts / well-scored jobs that match your skills),
mails are deduplicated per address, and with auto_send=false you review the
drafts before anything leaves your account. Cold-mailing is what gets Gmail
accounts throttled, so quality > volume.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ...extraction.contacts import extract_emails
from ...extraction.skills import extract_skills
from ...profile.profile import Profile
from ...resumes.selector import choose_resume
from ...settings import Settings
from ...storage.db import Repository
from .templates import compose_application

log = logging.getLogger(__name__)
_SKIP_DOMAINS = {"linkedin.com", "licdn.com"}


def _role_match(profile: Profile, text: str, roles: str) -> bool:
    haystack = f"{text}\n{roles}".lower()
    return bool(extract_skills(haystack) & set(profile.skills)) or any(
        r.lower() in haystack for r in profile.target_roles)


def draft_from_contacts(repo: Repository, profile: Profile, settings: Settings) -> int:
    """Create mail_queue rows for relevant, not-yet-mailed email contacts. Returns how many."""
    created = 0
    status = "approved" if settings.mail.auto_send else "pending"
    tdir = settings.path(settings.paths.templates_dir)
    for row in repo.unmailed_email_contacts():
        email, stype, sid = row["value"], row["source_type"], row["source_id"]
        domain = email.split("@", 1)[1]
        if email == profile.email.lower() or domain in _SKIP_DOMAINS:
            continue
        role, resume_skills = None, set()
        if stype == "post":
            post = repo.get_post(sid)
            if post is None or not post["is_hiring"] or not _role_match(profile, post["text"], post["roles"] or ""):
                continue
            role = (post["roles"] or "").split(",")[0].strip() or None
            resume_skills = extract_skills(post["text"])
        elif stype == "job":
            job = repo.get_job(sid)
            if job is None or (job["score"] or 0) < settings.apply.min_score or job["status"] == "skipped":
                continue
            role, resume_skills = job["title"], extract_skills(f'{job["title"]} {job["description"] or ""}')
        else:
            continue
        variant = choose_resume(profile, resume_skills, settings.root)
        resume_path = str(settings.path(variant.path)) if variant else ""
        subject, text, page = compose_application(profile, email, role, tdir, settings.mail.template)
        created += repo.queue_mail(email, subject, text, page, resume_path, stype, sid, status)
    log.info("created %d mail drafts (%s)", created, status)
    return created
