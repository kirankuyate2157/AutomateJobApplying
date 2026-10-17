"""Plain-text status report (also used by the end-of-run summary and the UI)."""
from __future__ import annotations

from datetime import date

from ..storage.db import Repository


def today_report(repo: Repository, daily_target: int) -> str:
    today = date.today().isoformat()
    by_status = dict(repo.conn.execute(
        "SELECT status, COUNT(*) FROM jobs WHERE substr(COALESCE(applied_at, first_seen),1,10)=? GROUP BY status",
        (today,)).fetchall())
    lines = [
        f"JobPilot report for {today}",
        f"  applied today          : {repo.count_applied_today()} / {daily_target}",
        "  today by status        : " + (", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "-"),
        f"  needs review (jobs)    : {repo.count('jobs', 'status=?', ('needs_review',))}",
        f"  questions to answer    : {repo.count('questions', 'status=?', ('pending',))}   -> jobpilot answers list",
        f"  legacy answers to check: {repo.count('questions', 'status=?', ('legacy',))}",
        f"  hiring posts stored    : {repo.count('posts', 'is_hiring=1')}",
        f"  contacts collected     : {repo.count('contacts')} "
        f"(emails {repo.count('contacts', 'kind=?', ('email',))}, phones {repo.count('contacts', 'kind=?', ('phone',))}, "
        f"forms {repo.count('contacts', 'kind=?', ('form',))})",
        f"  mails                  : pending {repo.count('mail_queue', 'status=?', ('pending',))}, "
        f"approved {repo.count('mail_queue', 'status=?', ('approved',))}, sent {repo.count('mail_queue', 'status=?', ('sent',))}",
    ]
    best = repo.conn.execute("SELECT key, seen, applied FROM search_stats ORDER BY applied DESC LIMIT 3").fetchall()
    if best:
        lines.append("  best searches          : " + "; ".join(f"{r['key'].split('|')[0]} ({r['applied']}/{r['seen']})" for r in best))
    return "\n".join(lines)
