"""Turn LinkedIn's relative timestamps into datetimes.

Handles job-card text ('3 hours ago', 'Reposted 2 weeks ago') and the short
post form ('3h', '2d', '1w', '1mo', '5m').
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_LONG = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_SHORT = re.compile(r"^\s*(\d+)\s*(mo|yr|w|d|h|m|s)\b", re.I)
_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
            "month": 2592000, "year": 31536000}                      # month=30d, year=365d approximations
_SHORT_MAP = {"s": "second", "m": "minute", "h": "hour", "d": "day", "w": "week", "mo": "month", "yr": "year"}


def parse_relative_time(text: str, now: datetime | None = None) -> datetime | None:
    """Return the absolute time, or None if the text is not a relative time."""
    now = now or datetime.now()
    text = text or ""
    if m := _LONG.search(text):
        return now - timedelta(seconds=int(m.group(1)) * _SECONDS[m.group(2).lower()])
    if m := _SHORT.match(text):
        return now - timedelta(seconds=int(m.group(1)) * _SECONDS[_SHORT_MAP[m.group(2).lower()]])
    return None
