"""Pull emails, phone numbers, application links, company and requirements out
of any text.

Used for BOTH LinkedIn hiring posts and job descriptions, so every contact a
recruiter leaves anywhere ends up in the same organised table.

Extraction strategy (lean, works offline):
  1. Regex/pattern extraction first - instant, free, deterministic.
  2. Optional LLM pass only when `llm.provider` is configured AND
     `posts.ai_extract` is on - fills gaps regex misses (company name,
     requirements hidden in prose). Falls back gracefully when no key.

SUGGESTION: add `resolve_short_links()` (follow lnkd.in/bit.ly redirects with
requests.head) so forms behind shorteners are classified correctly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol

from ..domain.models import Contact
from .skills import find_skills
from .skills import required_years

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- emails ---
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_BAD_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "pdf", "css", "js"}
_BAD_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "unsubscribe"}
_BAD_DOMAINS = {"example.com", "domain.com", "email.com", "yourcompany.com", "sentry.io"}


def _deobfuscate(text: str) -> str:
    """Turn 'hr [at] firm [dot] com' (a common anti-scraper habit) into a real address."""
    t = text.replace("＠", "@")
    t = re.sub(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*", "@", t, flags=re.I)
    return re.sub(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*", ".", t, flags=re.I)


def extract_emails(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _EMAIL.finditer(_deobfuscate(text or "")):
        email = m.group(0).lower().strip(".")
        local, _, domain = email.partition("@")
        if domain.rsplit(".", 1)[-1] in _BAD_TLDS or local in _BAD_LOCALS or domain in _BAD_DOMAINS:
            continue
        seen.setdefault(email)
    return list(seen)


# ----------------------------------------------------------------- links ----
_LINK = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'\)\]]+|\b(?:forms\.gle|lnkd\.in|bit\.ly|tinyurl\.com|t\.co)/[^\s<>\"'\)\]]+",
    re.I,
)
_FORM_HINTS = (
    "forms.gle",
    "docs.google.com/forms",
    "typeform.com",
    "tally.so",
    "jotform",
    "forms.office.com",
    "airtable.com/shr",
    "forms.zohopublic",
    "surveymonkey",
)
_ATS_HINTS = (
    "lever.co",
    "greenhouse.io",
    "workable.com",
    "ashbyhq.com",
    "smartrecruiters",
    "myworkdayjobs",
    "zohorecruit",
    "keka.com",
    "darwinbox",
    "bamboohr",
    "recruitee.com",
    "careers.",
    "/careers",
    "/jobs",
)
_SHORT_HINTS = ("lnkd.in", "bit.ly", "tinyurl.com", "t.co/")


def classify_link(url: str) -> str:
    u = url.lower()
    if any(h in u for h in _FORM_HINTS):
        return "form"
    if "linkedin.com/jobs" in u:
        return "linkedin_job"
    if any(h in u for h in _ATS_HINTS):
        return "ats"
    if any(h in u for h in _SHORT_HINTS):
        return "short"
    return "link"


def extract_links(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _LINK.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?)\"'")
        # profile/hashtag/feed links are noise for our purposes
        if re.search(r"linkedin\.com/(in|company|feed|hashtag|posts)/", url, re.I):
            continue
        seen.setdefault(url)
    return list(seen)


# ---------------------------------------------------------------- phones ----
# Indian mobiles start with 6-9 and have 10 digits (optionally +91 / 0 prefix).
_PHONE_IN = re.compile(r"(?<![\d\w])(?:\+?91[\s\-.]?)?0?([6-9]\d{4}[\s\-.]?\d{5})(?![\d\w])")
_PHONE_INTL = re.compile(
    r"(?<![\d\w])\+(?!91)(\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4})(?![\d\w])"
)


def extract_phones(text: str) -> list[str]:
    # URLs contain long digit runs (post ids, tracking ids): strip them first
    cleaned = _LINK.sub(" ", text or "")
    cleaned = _EMAIL.sub(" ", cleaned)
    found: dict[str, None] = {}
    for m in _PHONE_IN.finditer(cleaned):
        found.setdefault("+91" + re.sub(r"\D", "", m.group(1)))
    for m in _PHONE_INTL.finditer(cleaned):
        digits = re.sub(r"\D", "", m.group(1))
        if 8 <= len(digits) <= 14:
            found.setdefault("+" + digits)
    return list(found)


# ------------------------------------------------------ company + requirements
# Company name hints (heuristic - LinkedIn posts rarely state it explicitly).
_COMPANY_PATTERNS = [
    r"we(?:'re| are)\s+(?:are\s+)?(?:hiring|looking for)\s+(?:at|with)\s+([A-Z][A-Za-z0-9 &.\-]{2,40})",
    r"([A-Z][A-Za-z0-9 &.\-]{2,40})\s+(?:is|are)\s+hiring\b",
    r"hiring\s+(?:at|with)\s+([A-Z][A-Za-z0-9 &.\-]{2,40})",
    r"join\s+(?:the\s+)?([A-Z][A-Za-z0-9 &.\-]{2,40})\s+(?:team|family)",
    r"([A-Z][A-Za-z0-9 &.\-]{2,40})\s+is\s+(?:looking for|seeking)\s+(?:a|an)?\s*\w+\s+developer",
]
_COMPANY_STOPWORDS = {
    "hiring",
    "looking",
    "seeking",
    "apply",
    "application",
    "resume",
    "cv",
    "team",
    "family",
    "join",
    "we",
    "our",
    "the",
    "a",
    "an",
}


def _clean_company(name: str) -> str:
    name = re.sub(r"[.…:;,!]+$", "", name.strip())
    parts = [p for p in name.split() if p.lower() not in _COMPANY_STOPWORDS]
    name = " ".join(parts)
    return name[:60]


def extract_company(text: str) -> str:
    """Best-guess company name from a hiring post, or empty string (lowercased)."""
    for rx in _COMPANY_PATTERNS:
        m = re.search(rx, text or "", re.I)
        if m:
            name = _clean_company(m.group(1)).lower()
            if len(name) >= 2:
                return name
    return ""


def extract_requirements(text: str) -> dict[str, Any]:
    """Experience years (min,max) + skills mentioned in a post."""
    lo, hi = required_years(text or "")
    skills = find_skills(text or "")
    years = None
    if lo is not None:
        years = f"{lo}-{hi} years" if hi else f"{lo}+ years"
    return {"years": years, "skills": skills, "min_years": lo, "max_years": hi}


# ------------------------------------------------------- hiring-post logic --
# (regex, weight). Positive = looks like an employer/recruiter hiring post.
_HIRING_SIGNALS: list[tuple[str, int]] = [
    (r"\bwe(?:'re| are)\s+hiring\b", 3),
    (r"\bhiring\b", 2),
    (r"#hiring\b", 2),
    (r"\bsend (?:your |ur )?(?:resume|cv)\b", 3),
    (r"\b(?:share|drop|email|mail) (?:your |ur )?(?:resume|cv)\b", 3),
    (r"\bapply (?:now|here|at|via|using|through)\b", 2),
    (r"\bjob opening|\bopenings?\b|\bvacanc(?:y|ies)\b", 2),
    (r"\bwalk[- ]?in\b", 2),
    (r"\blooking for (?:a |an )?[\w\s/\-]{0,40}(?:developer|engineer|sde)\b", 2),
    (r"\bimmediate joiners?\b", 2),
    (r"\bjoin (?:our|my) team\b", 2),
    (r"\breferral\b", 1),
    (r"\bdm (?:me|us)\b", 1),
    (r"\bctc\b|\blpa\b", 1),
]
# job seekers also post about jobs; they must not be treated as hiring posts
_SEEKER_SIGNALS: list[tuple[str, int]] = [
    (r"#opentowork|open to work", -5),
    (r"\bi(?: am|'m) (?:currently )?(?:looking|seeking)\b", -4),
    (r"\bi (?:was|got|have been) laid off\b", -4),
    (r"\bmy (?:last|notice) (?:day|period)\b", -3),
    (r"\bplease (?:refer|help) me\b", -4),
    (r"\bhappy to share that i(?:'m| am) joining\b|\bstarting a new position\b", -4),
]
_ROLE = re.compile(
    r"\b((?:senior|sr\.?|junior|jr\.?|lead|staff|principal|associate)?\s*"
    r"(?:full[\s\-]?stack|back[\s\-]?end|front[\s\-]?end|software|python|java(?:script)?|node(?:\.?js)?|"
    r"react(?:\.?js)?|mern|devops|cloud|data|ml|ai|sde|web|mobile|android|ios|qa|sdet|application)\s*"
    r"(?:engineer|developer|programmer|architect|sde|intern)(?:\s*[-–]?\s*(?:i{1,3}|[1-3]))?)\b",
    re.I,
)


@dataclass
class PostAnalysis:
    hiring_score: int
    is_hiring: bool
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    company: str = ""  # hiring company (regex or AI)
    requirements: str = ""  # e.g. "3+ years | python, react, aws"

    def contacts(self, text: str = "") -> list[Contact]:
        """Flatten into Contact rows, with a short context snippet for review."""

        def ctx(needle: str) -> str:
            i = text.lower().find(needle.lower().replace("+91", ""))
            return " ".join(text[max(0, i - 40) : i + 60].split()) if i >= 0 else ""

        out = [Contact("email", e, ctx(e)) for e in self.emails]
        out += [Contact("phone", p, ctx(p[-10:])) for p in self.phones]
        out += [Contact(classify_link(u), u, ctx(u)) for u in self.links]
        return out


# ----------------------------------------------------------------- optional AI ----
class LLMExtractor(Protocol):
    def complete(self, prompt: str) -> str: ...


class AIPostExtractor:
    """Uses the LLM to extract company, requirements and emails from a post.

    Only used when an LLM key is configured AND the caller asks for it. The
    LLM is told to use ONLY facts in the post, so it cannot invent companies.
    Returns a dict with company, requirements, emails; empty values on failure.
    """

    def __init__(self, llm: LLMExtractor | None, profile_text: str = ""):
        self.llm = llm
        self.profile_text = profile_text

    def extract(self, post_text: str) -> dict[str, Any]:
        if self.llm is None:
            return {}
        prompt = (
            "You extract hiring info from ONE LinkedIn post. Use ONLY facts in "
            "the POST below. Never invent a company, email or requirement.\n"
            'Return ONLY JSON: {"company": "...", "requirements": "...", '
            '"emails": ["..."]}\n'
            'If a field is not present in the post, set it to "" or [].\n\n'
            f"CANDIDATE PROFILE (for context only, do not copy into answers):\n"
            f"{self.profile_text}\n\n"
            f"POST:\n{post_text}\n"
        )
        try:
            out = self.llm.complete(prompt)
        except Exception as exc:  # network / key / rate limit: fall back to regex
            log.debug("AI post extraction failed: %s", exc)
            return {}
        import json as _json

        m = re.search(r"\{.*\}", out or "", re.S)
        if not m:
            return {}
        try:
            obj = _json.loads(m.group(0))
        except ValueError:
            return {}
        return {
            "company": str(obj.get("company", "") or "").strip().lower(),
            "requirements": str(obj.get("requirements", "") or "").strip(),
            "emails": [str(e).strip().lower() for e in (obj.get("emails") or []) if str(e).strip()],
        }


def analyze_post(
    text: str,
    extra_hrefs: list[str] | None = None,
    min_score: int = 3,
    ai_extractor: AIPostExtractor | None = None,
) -> PostAnalysis:
    """Score a post for hiring intent and extract every way to apply.

    `extra_hrefs` are anchor targets scraped from the DOM: mailto: links and
    external URLs that the visible text may truncate with '…'.

    `ai_extractor` (optional) refines company/requirements/emails with the LLM;
    regex results are used when AI is unavailable or returns nothing.
    """
    text = text or ""
    hrefs = extra_hrefs or []
    blob = text + "\n" + "\n".join(hrefs)
    score = sum(w for rx, w in _HIRING_SIGNALS + _SEEKER_SIGNALS if re.search(rx, text, re.I))
    emails = extract_emails(blob.replace("mailto:", " "))
    phones = extract_phones(text)
    links = extract_links(blob)
    # WHY a concrete contact boosts the score: "send CV to x@y.com" is a very
    # strong signal even when the post never says the word 'hiring'.
    if emails and score > -3:
        score += 1
    is_hiring = score >= min_score or (
        score >= 2 and bool(emails or any(classify_link(u) in ("form", "ats") for u in links))
    )
    roles: dict[str, None] = {}
    for m in _ROLE.finditer(text):
        roles.setdefault(" ".join(m.group(1).split()).title())

    # ---- company + requirements: regex first (free, offline) ---------------
    company = extract_company(text)
    req = extract_requirements(text)
    requirements = req["years"] or ""
    if req["skills"]:
        requirements = (requirements + " | " if requirements else "") + ", ".join(req["skills"])

    # ---- optional AI pass: fill gaps regex missed --------------------------
    ai = ai_extractor.extract(text) if ai_extractor is not None else {}
    if ai:
        if not company and ai.get("company"):
            company = str(ai["company"]).lower().strip()
        if not requirements and ai.get("requirements"):
            requirements = str(ai["requirements"]).strip()
        # AI emails supplement regex emails (dedupe)
        for e in ai.get("emails", []):
            if e and e not in emails:
                emails.append(e)

    return PostAnalysis(
        score,
        is_hiring,
        emails,
        phones,
        links,
        list(roles),
        company=company,
        requirements=requirements,
    )
