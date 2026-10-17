"""Store every contact found in a piece of text, tagged with where it came from.

One function used by BOTH the job pipeline (job descriptions: "mail your CV to
hr@x.com") and the post pipeline, so all contacts land in the same table.
"""
from __future__ import annotations

from ..storage.db import Repository
from .contacts import analyze_post


def harvest_text(repo: Repository, text: str, source_type: str, source_id: str,
                 hrefs: list[str] | None = None) -> int:
    """Returns the number of NEW contacts stored (duplicates are ignored by the DB)."""
    analysis = analyze_post(text, hrefs)
    new = 0
    for contact in analysis.contacts(text):
        new += repo.add_contact(contact.kind, contact.value, source_type, source_id, contact.context)
    return new
