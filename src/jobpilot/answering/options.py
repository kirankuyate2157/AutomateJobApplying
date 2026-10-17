"""Map a desired answer onto the actual options of a select/radio field.

WHY: the legacy bot required exact label matches and otherwise clicked a
RANDOM option. Here we match robustly (yes/no synonyms, 'Decline' phrasing,
numeric ranges, fuzzy text) and return None when nothing fits, so the caller
can ask the LLM or queue the question for review instead of guessing.
"""
from __future__ import annotations

import difflib
import re

_PLACEHOLDERS = {"select an option", "select", "choose", "please select", "-- select --", ""}
_YES = {"yes", "y", "true", "agree", "i agree", "i do", "i have", "checked", "ok", "okay"}
_NO = {"no", "n", "false", "disagree", "i do not", "i dont", "i don't", "unchecked"}
_DECLINE_HINTS = ("decline", "prefer not", "not wish", "don't wish", "do not wish", "not want", "not to say")


def is_placeholder(option: str) -> bool:
    return option.strip().lower() in _PLACEHOLDERS


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+ ]", "", s.lower().replace("’", "'")).strip()


def real_options(options: list[str]) -> list[str]:
    return [o for o in options if not is_placeholder(o)]


def best_option(answer: str, options: list[str]) -> str | None:
    """Return the option text that best represents `answer`, or None."""
    opts = real_options(options)
    if not opts or answer is None:
        return None
    a = _norm(str(answer))
    if not a:
        return None
    normed = {o: _norm(o) for o in opts}

    for o, n in normed.items():                          # 1. exact
        if n == a:
            return o
    if a in _YES or a in _NO:                            # 2. yes/no families
        wanted = ("yes", "i agree", "agree", "i do", "i have") if a in _YES else ("no", "i do not", "disagree", "i dont")
        for w in wanted:
            for o, n in normed.items():
                if n == w or n.startswith(w + " "):
                    return o
    if a == "decline" or any(h in a for h in _DECLINE_HINTS):   # 3. decline phrasing
        for o in opts:
            if any(h in o.lower() for h in _DECLINE_HINTS):
                return o
    contained = [o for o, n in normed.items() if a in n or (n and n in a)]   # 4. containment
    if len(contained) == 1:
        return contained[0]
    close = difflib.get_close_matches(a, list(normed.values()), n=1, cutoff=0.75)   # 5. fuzzy
    if close:
        return next(o for o, n in normed.items() if n == close[0])
    return None


_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)")
_PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*\+|(?:more than|over|above|at least)\s*(\d+(?:\.\d+)?)", re.I)
_LESS = re.compile(r"(?:less than|under|below|up to|upto|<)\s*(\d+(?:\.\d+)?)", re.I)


def range_option(value: float, options: list[str]) -> str | None:
    """Pick the bucket containing `value` among options like '0-1', '3-5', '5+', 'Less than 1'."""
    for o in real_options(options):
        low = o.lower()
        if (m := _RANGE.search(low)) and float(m.group(1)) <= value <= float(m.group(2)):
            return o
        if (m := _LESS.search(low)) and value < float(m.group(1)):
            return o
        if (m := _PLUS.search(low)) and value >= float(m.group(1) or m.group(2)):
            return o
        if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*(?:years?|yrs?)?\s*", low) and float(re.findall(r"\d+(?:\.\d+)?", low)[0]) == value:
            return o
    return None
