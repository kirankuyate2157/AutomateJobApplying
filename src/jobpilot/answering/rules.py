"""Deterministic answers derived from the profile (no network, no cost).

HOW IT WORKS: each @rule has a regex tested against the question label. The
first rule (in registration order) that returns a value wins, with its own
confidence. ORDER MATTERS: specific rules are registered before generic ones.

HOW TO ADD A RULE (the extension point for new question types):

    @rule("my_rule", r"some regex", confidence=0.9)
    def _(ctx, m): return ctx.profile.something

Confidence below `answers.min_confidence` (default 0.7) means "probably right
but not safe": the engine then falls through to the LLM / review queue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..domain.models import Job
from ..extraction.skills import GENERIC_EXPERIENCE_WORDS, SKILLS, find_skills
from ..profile.profile import Profile
from .options import best_option, is_placeholder, range_option, real_options


@dataclass
class Ctx:
    label: str
    kind: str                       # text | number | textarea | select | radio | checkbox
    options: list[str]
    profile: Profile
    job: Job | None = None

    @property
    def low(self) -> str:
        return self.label.lower()

    @property
    def yes_no(self) -> bool:
        opts = {o.strip().lower() for o in real_options(self.options)}
        return bool(opts) and opts <= {"yes", "no"} or bool(
            re.match(r"\s*(do|does|did|have|has|are|is|can|will|would|were)\b", self.low))


@dataclass
class _Rule:
    name: str
    rx: re.Pattern[str]
    fn: Callable[[Ctx, re.Match[str]], object]
    confidence: float
    max_words: int | None = None     # only fire on SHORT labels ("City", not "Are you ok with this city?")
    skip_yes_no: bool = False        # data-entry rules must not answer Yes/No questions


_RULES: list[_Rule] = []


def rule(name: str, pattern: str, confidence: float = 0.9, max_words: int | None = None,
         skip_yes_no: bool = False):
    """Register a rule. The two guards exist because bare keywords such as
    'country', 'state' or 'location' also appear inside long, unrelated
    questions ("Please state your expected CTC") and would answer them wrongly."""
    def deco(fn):
        _RULES.append(_Rule(name, re.compile(pattern, re.I), fn, confidence, max_words, skip_yes_no))
        return fn
    return deco


def run_rules(ctx: Ctx) -> tuple[str, float, str] | None:
    """Return (answer, confidence, rule_name) or None."""
    for r in _RULES:
        m = r.rx.search(ctx.label)
        if not m:
            continue
        if r.max_words and len(ctx.label.split()) > r.max_words:
            continue
        if r.skip_yes_no and ctx.yes_no:
            continue
        value = r.fn(ctx, m)
        if value not in (None, ""):
            return str(value), r.confidence, r.name
    return None


def yn(flag: bool) -> str:
    return "Yes" if flag else "No"


def ynq(c: Ctx, flag: bool) -> str | None:
    """Yes/No answer ONLY when the field really is a yes/no question.

    WHY: answering "Yes" into a free-text "Highest degree" box is worse than
    leaving it for the LLM/review queue.
    """
    return yn(flag) if (c.yes_no or c.kind == "checkbox") else None


def _num(x: float) -> str:
    return f"{x:g}"


# ------------------------------------------------------------- employment ---
@rule("current_company", r"(current|present|most recent|last)\s*(company|employer|organi[sz]ation)", 0.92)
def _company(c, m):
    return c.profile.current_company or None


@rule("current_title", r"current\s*(job\s*)?(title|role|designation|position)", 0.9)
def _title(c, m):
    return c.profile.current_title or None


@rule("previous_employment", r"(previously|ever|formerly)\s+(worked|employed)|former employee|worked (for|at|with) .{1,40} before", 0.85)
def _previous(c, m):
    return ynq(c, False)


# --- notice period --------------------------------------------------------- #
_DAYS_PER = {"day": 1, "week": 7, "month": 30}


@rule("notice_period", r"notice|join(ing)? (date|within|immediately)|how soon|earliest.*(start|join)|availab\w* to (start|join)|immediate", 0.9)
def _notice(c, m):
    if c.kind == "textarea":
        return None
    days = c.profile.notice_period_days
    low = c.low
    if mm := re.search(r"(within|less than|under|up ?to|maximum|max|in)\s*(\d+)\s*(day|week|month)", low):
        return ynq(c, days <= int(mm.group(2)) * _DAYS_PER[mm.group(3)])
    if "immediate" in low and re.match(r"\s*(can|are|do|would|will)\b", low):
        return ynq(c, days <= 15)
    if c.kind in ("select", "radio") and c.options:
        return None            # bucket labels vary a lot: let the user decide once (cached)
    if "month" in low:
        return str(round(days / 30))
    if "week" in low:
        return str(round(days / 7))
    return str(days)


# --- compensation ---------------------------------------------------------- #
def _money(amount: int, low: str) -> str:
    if re.search(r"lakh|lpa|lac\b", low):
        return _num(amount / 100000)
    if re.search(r"month", low):
        return str(round(amount / 12))
    return str(amount)


@rule("expected_ctc", r"(expect|desired|target|asking)\w*.{0,20}(ctc|salary|compensation|pay)|salary expectation|(ctc|salary).{0,20}expect", 0.9)
def _expected(c, m):
    return _money(c.profile.expected_ctc, c.low) if c.profile.expected_ctc else None


@rule("current_ctc", r"(current|present|existing|last|drawn).{0,15}(ctc|salary|compensation|pay)|(ctc|salary).{0,15}current", 0.9)
def _current(c, m):
    return _money(c.profile.current_ctc, c.low) if c.profile.current_ctc else None


@rule("salary_generic", r"\bctc\b|salary|compensation", 0.75)
def _salary_generic(c, m):
    return _money(c.profile.expected_ctc, c.low) if c.profile.expected_ctc else None


# --- experience ------------------------------------------------------------ #
def _years_for(label: str, p: Profile) -> float | None:
    skills = find_skills(label)
    if skills:
        known = p.skill_years(skills[0])
        return known if known is not None else 0.0   # a recognised tech we do not have -> honest 0
    if any(w in label.lower() for w in GENERIC_EXPERIENCE_WORDS):
        return p.total_years
    return None


@rule("skill_experience_yesno",
      r"(do you have|have you|are you|did you).{0,40}(experience|worked|familiar|proficient|knowledge|hands[- ]on).{0,60}(with|in|on|using)", 0.88)
def _skill_yesno(c, m):
    years = _years_for(c.label, c.profile)
    if years is None:
        return None
    if mm := re.search(r"(\d+)\s*\+?\s*(?:or more\s*)?(?:years?|yrs?)", c.low):
        return ynq(c, years >= float(mm.group(1)))
    return ynq(c, years > 0)


@rule("years_experience", r"\b(years?|yrs?)\b", 0.88)
def _years(c, m):
    low = c.low
    if not re.search(r"experience|exp\b|worked|working|using|developing|programming|have you been|of work", low):
        return None
    years = _years_for(c.label, c.profile)
    if years is None:
        return None
    if c.yes_no:
        if mm := re.search(r"(\d+)\s*\+?\s*(?:or more\s*)?(?:years?|yrs?)", low):
            return yn(years >= float(mm.group(1)))
        return yn(years > 0)
    if c.options and not c.yes_no:
        return range_option(years, c.options)
    return _num(years)


# ------------------------------------------------------------ eligibility ---
@rule("sponsorship", r"sponsor", 0.95)
def _sponsor(c, m):
    return ynq(c, c.profile.requires_sponsorship)


@rule("work_authorization", r"authori[sz]ed|legally|work permit|right to work|eligible to work|work authori", 0.9)
def _auth(c, m):
    # the scorer already rejects jobs outside authorised countries, so reaching
    # here means the job is in a country the profile is authorised for
    return ynq(c, True)


@rule("relocate", r"relocat", 0.9)
def _relocate(c, m):
    return ynq(c, c.profile.willing_to_relocate)


@rule("work_mode", r"(comfortable|willing|able|ok|okay|open).{0,40}(on-?site|office|hybrid|commut|remote|work from)", 0.85)
def _mode(c, m):
    low = c.low
    modes = {x.lower() for x in c.profile.work_modes}
    if "remote" in low or "work from home" in low:
        return ynq(c, "remote" in modes)
    if "hybrid" in low:
        return ynq(c, "hybrid" in modes)
    return ynq(c, "onsite" in modes or "on-site" in modes)


@rule("degree", r"bachelor|master|phd|doctorate|b\.?tech|m\.?tech|graduate|degree|diploma", 0.85)
def _degree(c, m):
    low, have = c.low, {d.lower() for d in c.profile.degrees}
    if re.search(r"phd|doctorate", low):
        return ynq(c, "phd" in have)
    if "master" in low or "m.tech" in low or "mtech" in low:
        return ynq(c, "master" in have or "phd" in have)
    if re.search(r"bachelor|b\.?tech|graduate|degree", low):
        return ynq(c, bool(have & {"bachelor", "master", "phd"}))
    return None


@rule("background_check", r"background (check|verification)|drug (test|screen)|reference check", 0.9)
def _bg(c, m):
    return ynq(c, True)


# ------------------------------------------------------------ demographics ---
def _demo(c: Ctx, key: str) -> str:
    return c.profile.demographics.get(key, "Decline")


@rule("gender", r"\bgender\b|\bsex\b|pronoun", 0.9)
def _gender(c, m):
    return _demo(c, "gender")


@rule("ethnicity", r"ethnic|\brace\b|racial", 0.9)
def _ethnicity(c, m):
    return _demo(c, "ethnicity")


@rule("veteran", r"veteran|military|protected", 0.9)
def _veteran(c, m):
    return _demo(c, "veteran")


@rule("disability", r"disab|handicap", 0.9)
def _disability(c, m):
    return _demo(c, "disability")


# ----------------------------------------------------------- contact info ---
@rule("phone_country_code", r"country.*code|phone.*code", 0.95)
def _phone_code(c, m):
    return f"{c.profile.phone_country} ({c.profile.phone_code})"


@rule("email", r"e-?mail", 0.95, max_words=8, skip_yes_no=True)
def _email(c, m):
    if c.options:   # LinkedIn shows the account's own addresses; prefer ours, else the first real one
        return best_option(c.profile.email, c.options) or next(iter(real_options(c.options)), None)
    return c.profile.email


@rule("phone", r"phone|mobile|contact number|whatsapp", 0.95, max_words=8, skip_yes_no=True)
def _phone(c, m):
    return c.profile.phone


@rule("first_name", r"\b(first|given)\s*name", 0.97, max_words=8, skip_yes_no=True)
def _first(c, m):
    return c.profile.first_name


@rule("last_name", r"\b(last|family|sur)\s*name", 0.97, max_words=8, skip_yes_no=True)
def _last(c, m):
    return c.profile.last_name


@rule("middle_name", r"\bmiddle\s*name", 0.9)
def _middle(c, m):
    return c.profile.middle_name or None


@rule("full_name", r"full name|your name|legal name|signature|^name\b", 0.9, max_words=8, skip_yes_no=True)
def _full(c, m):
    return c.profile.full_name


@rule("linkedin", r"linked\s?in", 0.95, max_words=8, skip_yes_no=True)
def _linkedin(c, m):
    return c.profile.linkedin_url or None


@rule("github", r"github", 0.95, max_words=8, skip_yes_no=True)
def _github(c, m):
    return c.profile.github_url or None


@rule("portfolio", r"portfolio|website|personal (site|url)|blog", 0.9, max_words=8, skip_yes_no=True)
def _portfolio(c, m):
    return c.profile.portfolio_url or c.profile.github_url or None


@rule("zip", r"\bzip|postal|pin ?code", 0.95, max_words=8, skip_yes_no=True)
def _zip(c, m):
    return c.profile.zip_code or None


@rule("street", r"street|address line|home address", 0.85, max_words=5, skip_yes_no=True)
def _street(c, m):
    return c.profile.street or c.profile.city or None


@rule("country", r"\bcountry\b", 0.9, max_words=5, skip_yes_no=True)
def _country(c, m):
    return c.profile.country


@rule("state", r"\b(state|province)\b", 0.9, max_words=5, skip_yes_no=True)
def _state(c, m):
    return c.profile.state or None


@rule("city", r"\bcity\b|current location|where are you (based|located)|\blocation\b|residing|reside", 0.88, max_words=5, skip_yes_no=True)
def _city(c, m):
    return c.profile.city or None


# ------------------------------------------------------------ free-form -----
@rule("headline", r"headline", 0.9)
def _headline(c, m):
    return c.profile.headline or None


@rule("cover_letter", r"cover letter", 0.9)
def _cover(c, m):
    return c.profile.cover_letter.strip() or None


@rule("summary", r"summary|about (you|yourself)|tell us about yourself|introduce yourself", 0.85)
def _summary(c, m):
    return c.profile.summary.strip() or None


@rule("referral_source", r"how did you (hear|find|learn)|where did you (hear|find)", 0.9)
def _source(c, m):
    return "LinkedIn"


@rule("self_rating", r"scale of 1|rate yourself|rating of 1|1\s*(-|to)\s*10", 0.75)
def _rating(c, m):
    return c.profile.self_rating


@rule("consent", r"\b(agree|acknowledge|consent|certify|terms|privacy|confirm that|declare)\b", 0.9)
def _consent(c, m):
    return ynq(c, True)


# generic willingness is deliberately LOW confidence: "willing to work nights?"
# is not something to auto-confirm. Falls through to LLM / review queue.
@rule("generic_willingness", r"(are you|would you|do you).{0,20}(willing|comfortable|open to|ok with|okay with|able to|can you)", 0.6)
def _willing(c, m):
    return ynq(c, True)


def known_skill_names() -> list[str]:
    return sorted(SKILLS)
