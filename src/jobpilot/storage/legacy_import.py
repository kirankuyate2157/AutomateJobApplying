"""Import the history written by the old bot (all_applied_applications_history.csv).

Two goals:
  1. NEVER re-apply to jobs the old bot already handled -> import job ids.
  2. Reuse the questions it met -> import them into the question bank.

WHY legacy answers become status='legacy' (not 'user'): the old bot often
answered unknown questions with "Yes"/"0"/a random option. They are shown in
`jobpilot answers list --status legacy` for a quick review; `answers
promote-legacy` approves them in bulk once you have looked.
"""
from __future__ import annotations

import ast
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ..answering.normalize import normalize_question
from .db import Repository

# questions the rule engine answers better than any stored legacy value
_SKIP_KEYS = ("email", "phone", "country code", "first name", "last name", "full name")
_OPTION = re.compile(r'"([^"]*)"(?:<[^>]*>)?')


@dataclass
class ImportReport:
    jobs: int = 0
    jobs_skipped: int = 0
    questions: int = 0
    questions_skipped: int = 0


def _split_label(raw: str) -> tuple[str, list[str]]:
    """'Question? [  "Yes"<Yes>, "No"<No>, ]' -> ('Question?', ['Yes', 'No'])"""
    base, _, rest = raw.partition(" [")
    return base.strip(), [o for o in _OPTION.findall(rest) if o and o.lower() != "select an option"]


def _clean_answer(answer: object) -> str:
    text = str(answer)
    m = _OPTION.match(text.strip())            # radio answers look like '"Yes"<Yes>'
    return (m.group(1) if m else text).strip()


def import_legacy_csv(repo: Repository, path: str | Path) -> ImportReport:
    csv.field_size_limit(10_000_000)           # old files contain huge job descriptions
    report = ImportReport()
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            job_id = (row.get("Job ID") or "").strip()
            if job_id:
                easy = (row.get("External Job link") or "").strip() in ("Easy Applied", "")
                applied_at = (row.get("Date Applied") or "").strip()
                if applied_at.lower() == "pending":
                    applied_at = ""
                added = repo.import_applied(
                    job_id, row.get("Title", ""), row.get("Company", ""), row.get("Job Link", ""),
                    applied_at, "applied" if easy else "external",
                    "" if easy else row.get("External Job link", ""))
                report.jobs += added
                report.jobs_skipped += not added
            _import_questions(repo, row.get("Questions Found") or "", report)
    return report


def _import_questions(repo: Repository, cell: str, report: ImportReport) -> None:
    if not cell.strip():
        return
    try:
        entries = ast.literal_eval(cell)       # the old bot stored str(set_of_tuples)
    except (ValueError, SyntaxError):
        return
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) < 3:
            continue
        raw_label, answer, qtype = entry[0], entry[1], entry[2]
        label, options = _split_label(str(raw_label))
        key = normalize_question(label)
        if not key or key == "unknown" or qtype == "checkbox" or any(s in key for s in _SKIP_KEYS):
            report.questions_skipped += 1
            continue
        value = _clean_answer(answer)
        if not value or value.lower() == "select an option":
            report.questions_skipped += 1
            continue
        if repo.get_question(key) is None:
            repo.record_question(key, label, qtype, options, value, "legacy", 0.4, "legacy")
            report.questions += 1
        else:
            report.questions_skipped += 1
