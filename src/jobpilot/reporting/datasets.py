"""Business-friendly views of the database for export, UI and reports.

WHY: raw tables are normalised for the program; people want e.g. "each contact
together with the post/author/URL it came from". Centralising these queries
means CSV, Excel and the web UI always show identical data.
"""
from __future__ import annotations

from typing import Any

from ..storage.db import Repository

Dataset = tuple[list[str], list[tuple[Any, ...]]]
_CELL_LIMIT = 30000          # Excel cells max out at 32,767 characters


def _query(repo: Repository, sql: str) -> Dataset:
    cur = repo.conn.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = [tuple(_clip(v) for v in r) for r in cur.fetchall()]
    return cols, rows


def _clip(value: Any) -> Any:
    return value[:_CELL_LIMIT] if isinstance(value, str) and len(value) > _CELL_LIMIT else value


def build_datasets(repo: Repository) -> dict[str, Dataset]:
    return {
        "applications": _query(repo, """
            SELECT job_id, title, company, location, work_style, status, reason, score, resume,
                   url, external_url, applied_at, first_seen, query
            FROM jobs WHERE status IN ('applied','dry_run_ok','needs_review','external','failed')
            ORDER BY COALESCE(applied_at, first_seen) DESC"""),
        "contacts": _query(repo, """
            SELECT c.kind, c.value, c.source_type, c.source_id,
                   COALESCE(p.author, j.company, '') AS from_who,
                   COALESCE(p.url, j.url, '') AS source_url,
                   COALESCE(p.roles, j.title, '') AS roles_or_title,
                   c.context, c.first_seen
            FROM contacts c
            LEFT JOIN posts p ON c.source_type='post' AND p.post_id=c.source_id
            LEFT JOIN jobs  j ON c.source_type='job'  AND j.job_id=c.source_id
            ORDER BY c.id DESC"""),
        "hiring_posts": _query(repo, """
            SELECT post_id, author, posted_text, roles, hiring_score, url, query, first_seen, text
            FROM posts WHERE is_hiring=1 ORDER BY first_seen DESC"""),
        "mail_queue": _query(repo, """
            SELECT id, to_email, status, subject, resume_path, error, created_at, sent_at
            FROM mail_queue ORDER BY id DESC"""),
        "questions": _query(repo, """
            SELECT text AS question, qtype, answer, source, status, times_seen, last_seen
            FROM questions ORDER BY (status='pending') DESC, times_seen DESC"""),
        "search_yield": _query(repo, """
            SELECT key AS search, seen, applied, runs, last_run,
                   ROUND(1.0*applied/NULLIF(seen,0), 3) AS apply_rate
            FROM search_stats ORDER BY applied DESC"""),
        "runs": _query(repo, "SELECT * FROM runs ORDER BY id DESC"),
        "all_jobs": _query(repo, """
            SELECT job_id, title, company, location, status, reason, score, posted_at, url, first_seen
            FROM jobs ORDER BY first_seen DESC"""),
    }
