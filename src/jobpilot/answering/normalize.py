"""Canonical form of a question label, used as the question-bank key.

WHY: LinkedIn repeats labels with decoration ("Phone *", "Phone (required)",
"Phone\\nPhone") and the legacy dump stores options inside the label. Normalising
makes the same question hit the same bank row every time.
"""
from __future__ import annotations

import re


def clean_label(raw: str) -> str:
    """Undo LinkedIn's duplicated visible + screen-reader text."""
    lines = []
    for line in (raw or "").splitlines():
        line = " ".join(line.split())
        if line and line not in lines:
            lines.append(line)
    text = " ".join(lines)
    half = len(text) // 2
    if len(text) > 2 and len(text) % 2 == 1 and text[:half] == text[half + 1:]:   # "Phone Phone"
        text = text[:half]
    return re.sub(r"\s*\*\s*$|\(required\)|\brequired\b$", "", text, flags=re.I).strip()


def normalize_question(label: str) -> str:
    text = clean_label(label).lower()
    text = re.sub(r"\[.*?\]", " ", text)             # legacy 'label [ "opt1", "opt2" ]' form
    text = re.sub(r"[^a-z0-9+#. ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:300]
