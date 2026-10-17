"""SQLite repository: the single source of truth for everything JobPilot learns.

WHY SQLite instead of the legacy CSV files:
  * atomic writes (the legacy mail CSV update silently lost status)
  * dedupe via UNIQUE constraints instead of loading whole files into sets
  * easy queries ("applied today", "yield per search")
  * still exportable to CSV/Excel any time (see reporting/exporters.py)

MIGRATIONS are append-only: never edit an old entry, add a new one. The schema
version is stored in PRAGMA user_version so upgrades are automatic.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from ..domain.models import Job

MIGRATIONS: list[str] = [
    # ---- v1 -------------------------------------------------------------- #
    """
    CREATE TABLE jobs(
        job_id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, work_style TEXT,
        url TEXT, description TEXT, hr_name TEXT, hr_link TEXT, posted_at TEXT,
        query TEXT, score REAL, status TEXT NOT NULL DEFAULT 'seen', reason TEXT,
        resume TEXT, external_url TEXT, first_seen TEXT, applied_at TEXT);
    CREATE INDEX idx_jobs_status ON jobs(status);

    CREATE TABLE questions(
        key TEXT PRIMARY KEY, text TEXT, qtype TEXT, options_json TEXT,
        answer TEXT, source TEXT, confidence REAL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
        times_seen INTEGER DEFAULT 1, first_seen TEXT, last_seen TEXT);

    CREATE TABLE posts(
        post_id TEXT PRIMARY KEY, url TEXT, author TEXT, text TEXT, posted_text TEXT,
        query TEXT, is_hiring INTEGER, hiring_score INTEGER, roles TEXT, first_seen TEXT);

    CREATE TABLE contacts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, value TEXT NOT NULL,
        source_type TEXT, source_id TEXT, context TEXT, first_seen TEXT,
        UNIQUE(kind, value));

    CREATE TABLE mail_queue(
        id INTEGER PRIMARY KEY AUTOINCREMENT, to_email TEXT NOT NULL UNIQUE,
        subject TEXT, body_text TEXT, body_html TEXT, resume_path TEXT,
        status TEXT NOT NULL DEFAULT 'pending', source_type TEXT, source_id TEXT,
        error TEXT, created_at TEXT, sent_at TEXT);

    CREATE TABLE search_stats(
        key TEXT PRIMARY KEY, seen INTEGER DEFAULT 0, applied INTEGER DEFAULT 0,
        runs INTEGER DEFAULT 0, last_run TEXT);

    CREATE TABLE runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
        dry_run INTEGER, applied INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0, review INTEGER DEFAULT 0, notes TEXT);
    """,
    # ---- v2+ : add new migrations below, never edit the ones above ------- #
]

# jobs in these states are never reconsidered (dry_run_ok is handled specially)
FINAL_STATUSES = ("applied", "skipped", "external", "failed")
EXPORTABLE_TABLES = ("jobs", "questions", "posts", "contacts", "mail_queue", "search_stats", "runs")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


class Repository:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")   # UI can read while the bot writes
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(sql)
            self.conn.execute(f"PRAGMA user_version = {i}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ jobs
    def upsert_job(self, job: Job, query: str = "", score: float | None = None) -> None:
        """Insert a job or refresh its scraped fields. Never resets its status."""
        self.conn.execute(
            """INSERT INTO jobs(job_id,title,company,location,work_style,url,description,hr_name,
                                hr_link,posted_at,query,score,status,first_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'seen', ?)
               ON CONFLICT(job_id) DO UPDATE SET title=excluded.title, company=excluded.company,
                 location=excluded.location, work_style=excluded.work_style,
                 description=excluded.description, hr_name=excluded.hr_name,
                 hr_link=excluded.hr_link, score=COALESCE(excluded.score, jobs.score)""",
            (job.job_id, job.title, job.company, job.location, job.work_style, job.url,
             job.description, job.hr_name, job.hr_link,
             job.posted_at.isoformat(timespec="seconds") if job.posted_at else None,
             query or job.query, score, _now()))
        self.conn.commit()

    def set_job_status(self, job_id: str, status: str, reason: str = "",
                       resume: str = "", external_url: str = "") -> None:
        applied_at = _now() if status in ("applied", "dry_run_ok") else None
        self.conn.execute(
            """UPDATE jobs SET status=?, reason=?, resume=COALESCE(NULLIF(?,''),resume),
                      external_url=COALESCE(NULLIF(?,''),external_url),
                      applied_at=COALESCE(?, applied_at) WHERE job_id=?""",
            (status, reason, resume, external_url, applied_at, job_id))
        self.conn.commit()

    def job_status(self, job_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return row["status"] if row else None

    def job_is_final(self, job_id: str, dry_run: bool) -> bool:
        """True if we must not touch this job again.

        WHY dry_run_ok is conditional: a dry run should not re-do the same jobs
        over and over, but once you go live those jobs must become eligible.
        'needs_review' is never final: it is retried after you answer the
        pending questions.
        """
        status = self.job_status(job_id)
        if status is None:
            return False
        return status in FINAL_STATUSES or (dry_run and status == "dry_run_ok")

    def count_applied_today(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='applied' AND substr(applied_at,1,10)=?",
            (_today(),)).fetchone()[0]

    def import_applied(self, job_id: str, title: str, company: str, url: str,
                       applied_at: str, status: str = "applied", external_url: str = "") -> bool:
        """Used by legacy import so old applications are never re-applied."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO jobs(job_id,title,company,url,status,applied_at,external_url,first_seen)
               VALUES(?,?,?,?,?,?,?,?)""",
            (job_id, title, company, url, status, applied_at, external_url, _now()))
        self.conn.commit()
        return cur.rowcount > 0

    def jobs_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE status=?", (status,)).fetchall()

    # ------------------------------------------------------------- questions
    def get_question(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM questions WHERE key=?", (key,)).fetchone()

    def record_question(self, key: str, text: str, qtype: str, options: list[str],
                        answer: str | None, source: str, confidence: float, status: str) -> None:
        """Log that a question was seen (and how it was answered).

        Precedence rules (decided in Python for readability):
          * a user-provided answer is never overwritten
          * a legacy suggestion is kept while the question is still unanswered
        """
        old = self.get_question(key)
        now = _now()
        if old is None:
            self.conn.execute(
                """INSERT INTO questions(key,text,qtype,options_json,answer,source,confidence,status,
                                         times_seen,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,1,?,?)""",
                (key, text, qtype, json.dumps(options), answer, source, confidence, status, now, now))
        else:
            if old["status"] == "user" or (old["status"] == "legacy" and status == "pending"):
                answer, source, confidence, status = (old["answer"], old["source"],
                                                      old["confidence"], old["status"])
            self.conn.execute(
                """UPDATE questions SET text=?, qtype=?, options_json=?, answer=?, source=?,
                          confidence=?, status=?, times_seen=times_seen+1, last_seen=? WHERE key=?""",
                (text, qtype, json.dumps(options), answer, source, confidence, status, now, key))
        self.conn.commit()

    def set_user_answer(self, key: str, answer: str) -> bool:
        cur = self.conn.execute(
            "UPDATE questions SET answer=?, source='user', confidence=1.0, status='user' WHERE key=?",
            (answer, key))
        self.conn.commit()
        return cur.rowcount > 0

    def list_questions(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute(
                "SELECT * FROM questions WHERE status=? ORDER BY times_seen DESC", (status,)).fetchall()
        return self.conn.execute("SELECT * FROM questions ORDER BY times_seen DESC").fetchall()

    def promote_legacy(self) -> int:
        """Accept all imported legacy answers as user-approved."""
        cur = self.conn.execute(
            "UPDATE questions SET status='user', source='user', confidence=1.0 "
            "WHERE status='legacy' AND answer IS NOT NULL AND answer<>''")
        self.conn.commit()
        return cur.rowcount

    # ----------------------------------------------------------------- posts
    def add_post(self, post_id: str, url: str, author: str, text: str, posted_text: str,
                 query: str, is_hiring: bool, hiring_score: int, roles: Iterable[str]) -> bool:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO posts(post_id,url,author,text,posted_text,query,is_hiring,
                                           hiring_score,roles,first_seen) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (post_id, url, author, text, posted_text, query, int(is_hiring), hiring_score,
             ", ".join(roles), _now()))
        self.conn.commit()
        return cur.rowcount > 0

    def post_known(self, post_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM posts WHERE post_id=?", (post_id,)).fetchone() is not None

    # -------------------------------------------------------------- contacts
    def add_contact(self, kind: str, value: str, source_type: str, source_id: str,
                    context: str = "") -> bool:
        """Returns True only for brand-new contacts (UNIQUE(kind,value) dedupes)."""
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO contacts(kind,value,source_type,source_id,context,first_seen)
               VALUES(?,?,?,?,?,?)""",
            (kind, value, source_type, source_id, context[:300], _now()))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ mail
    def queue_mail(self, to_email: str, subject: str, body_text: str, body_html: str,
                   resume_path: str, source_type: str, source_id: str, status: str = "pending") -> bool:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO mail_queue(to_email,subject,body_text,body_html,resume_path,
                                                status,source_type,source_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (to_email, subject, body_text, body_html, resume_path, status, source_type, source_id, _now()))
        self.conn.commit()
        return cur.rowcount > 0

    def mail_batch(self, statuses: Iterable[str], limit: int) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(list(statuses := list(statuses))))
        return self.conn.execute(
            f"SELECT * FROM mail_queue WHERE status IN ({marks}) ORDER BY id LIMIT ?",
            (*statuses, limit)).fetchall()

    def mark_mail(self, mail_id: int, status: str, error: str = "") -> None:
        self.conn.execute(
            "UPDATE mail_queue SET status=?, error=?, sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END WHERE id=?",
            (status, error, status, _now(), mail_id))
        self.conn.commit()

    def approve_pending_mail(self) -> int:
        cur = self.conn.execute("UPDATE mail_queue SET status='approved' WHERE status='pending'")
        self.conn.commit()
        return cur.rowcount

    def count_mail_sent_today(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM mail_queue WHERE status='sent' AND substr(sent_at,1,10)=?",
            (_today(),)).fetchone()[0]

    def count_mail_to_domain_today(self, domain: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM mail_queue WHERE status='sent' AND substr(sent_at,1,10)=? "
            "AND lower(to_email) LIKE ?", (_today(), f"%@{domain.lower()}")).fetchone()[0]

    # ---------------------------------------------------------- search stats
    def record_search(self, key: str, seen: int, applied: int) -> None:
        self.conn.execute(
            """INSERT INTO search_stats(key,seen,applied,runs,last_run) VALUES(?,?,?,1,?)
               ON CONFLICT(key) DO UPDATE SET seen=seen+excluded.seen, applied=applied+excluded.applied,
                 runs=runs+1, last_run=excluded.last_run""", (key, seen, applied, _now()))
        self.conn.commit()

    def search_stats(self) -> dict[str, tuple[int, int, int]]:
        rows = self.conn.execute("SELECT key,seen,applied,runs FROM search_stats").fetchall()
        return {r["key"]: (r["seen"], r["applied"], r["runs"]) for r in rows}

    # ------------------------------------------------------------------ runs
    def start_run(self, dry_run: bool) -> int:
        cur = self.conn.execute("INSERT INTO runs(started_at,dry_run) VALUES(?,?)", (_now(), int(dry_run)))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, applied: int, skipped: int, failed: int,
                   review: int, notes: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, applied=?, skipped=?, failed=?, review=?, notes=? WHERE id=?",
            (_now(), applied, skipped, failed, review, notes, run_id))
        self.conn.commit()

    # --------------------------------------------------------------- generic
    def fetch_table(self, table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        """Whitelisted table dump used by exporters and the UI."""
        if table not in EXPORTABLE_TABLES:
            raise ValueError(f"table {table!r} is not exportable")
        cur = self.conn.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cur.description]
        return cols, [tuple(r) for r in cur.fetchall()]

    def count(self, table: str, where: str = "1=1", params: tuple = ()) -> int:
        if table not in EXPORTABLE_TABLES:
            raise ValueError(table)
        return self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
