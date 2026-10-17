"""Application-email composition from the profile + editable templates.

Templates live in config/templates/<name>.txt and <name>.html (created by
`jobpilot init`) using $placeholders (string.Template). If a file is missing the
built-in default below is used, so the system always works out of the box.

Available placeholders: $greeting $role $full_name $first_name $years $headline
$skills_line $projects_text $projects_html $links_text $links_html $email $phone
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from string import Template

from ...profile.profile import Profile

GENERIC_LOCALS = {"hr", "hrd", "info", "jobs", "job", "career", "careers", "talent", "hiring", "recruit",
                  "recruiter", "recruitment", "team", "contact", "admin", "support", "resume", "cv", "apply",
                  "mail", "office", "people", "work", "join", "staffing", "ta", "hello", "hi"}

DEFAULT_TEXT = """$greeting

I came across your hiring post and I am excited to apply for $role. I am a $headline with $years years of experience building production applications.

Key skills: $skills_line

Selected work:
$projects_text

My resume is attached. Profile links:
$links_text

I would welcome a chance to discuss how I can contribute. Thank you for your time.

Best regards,
$full_name
$phone | $email
"""

DEFAULT_HTML = """<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#222">
<p>$greeting</p>
<p>I came across your hiring post and I am excited to apply for <b>$role</b>. I am a $headline with <b>$years years</b> of experience building production applications.</p>
<p><b>Key skills:</b> $skills_line</p>
<p><b>Selected work:</b></p><ul>$projects_html</ul>
<p>My resume is attached. Profile links:</p><ul>$links_html</ul>
<p>I would welcome a chance to discuss how I can contribute. Thank you for your time.</p>
<p>Best regards,<br><b>$full_name</b><br>$phone | $email</p></div>
"""


def greeting_for(email: str) -> str:
    """'rahul.sharma@x.com' -> 'Hi Rahul,'; 'hr@x.com' -> 'Hello Hiring Team,'."""
    local = email.split("@", 1)[0].lower()
    first = re.split(r"[._\-+0-9]", local)[0]
    if not first or first in GENERIC_LOCALS or len(first) < 3 or not first.isalpha():
        return "Hello Hiring Team,"
    return f"Hi {first.capitalize()},"


def _links(profile: Profile) -> list[tuple[str, str]]:
    pairs = [("Portfolio", profile.portfolio_url), ("GitHub", profile.github_url), ("LinkedIn", profile.linkedin_url)]
    return [(n, u) for n, u in pairs if u]


def _load(template_dir: Path, name: str, ext: str, default: str) -> Template:
    path = template_dir / f"{name}.{ext}"
    return Template(path.read_text(encoding="utf-8") if path.exists() else default)


def compose_application(profile: Profile, to_email: str, role: str | None = None,
                        template_dir: Path | None = None, name: str = "application_email"
                        ) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body)."""
    role = role or profile.primary_role
    top_skills = sorted(profile.skills, key=lambda k: -profile.skills[k])[:10]
    links = _links(profile)
    values = dict(
        greeting=greeting_for(to_email), role=role, full_name=profile.full_name,
        first_name=profile.first_name, years=f"{profile.total_years:g}",
        headline=profile.headline or profile.current_title or "software engineer",
        skills_line=", ".join(top_skills) or "see resume",
        projects_text="\n".join(f"- {p}" for p in profile.projects[:4]) or "- see resume",
        projects_html="".join(f"<li>{html.escape(p)}</li>" for p in profile.projects[:4]) or "<li>see resume</li>",
        links_text="\n".join(f"- {n}: {u}" for n, u in links) or "- see resume",
        links_html="".join(f'<li>{n}: <a href="{html.escape(u)}">{html.escape(u)}</a></li>' for n, u in links),
        email=profile.email, phone=profile.phone)
    tdir = template_dir or Path("__none__")
    text = _load(tdir, name, "txt", DEFAULT_TEXT).safe_substitute(values)
    page = _load(tdir, name, "html", DEFAULT_HTML).safe_substitute(
        {k: (html.escape(v) if k in ("role", "full_name", "headline", "skills_line", "greeting") else v)
         for k, v in values.items()})
    subject = f"Application for {role} | {profile.total_years:g} YOE | {profile.full_name}"
    return subject, text, page
