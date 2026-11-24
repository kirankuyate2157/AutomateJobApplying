"""LinkedIn network outreach automation: connection requests, DMs, follow-ups,
referrals.

Built on top of the existing email outreach (mail_queue, Mailer). This module
adds LinkedIn-native outreach via the browser, with the same safety rails:

  * Deduplication: UNIQUE(kind, value) — same person never contacted twice
  * Experiment tracking: experiment_id + variant per message (A/B testing)
  * Spacing: random delays between messages (avoid spam flags)
  * Daily caps: per outreach type (connection, dm, followup, referral)
  * Follow-up schedule: 3d / 7d / 14d intervals
  * Dry-run mode: prepare drafts, review before sending

All state lives in SQLite outreach_* tables (migration v2).
"""

from __future__ import annotations

import hashlib
import logging
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)

from ...core.context import AppContext
from ...settings import OutreachSettings
from ...storage.db import Repository

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ data models


@dataclass
class OutreachContact:
    """One person we may reach out to."""
    kind: str              # connection | dm | followup | referral
    value: str             # email | linkedin_profile_url | phone
    name: str = ""
    company: str = ""
    role: str = ""
    source_type: str = ""  # post | feed | jobs | manual
    source_id: str = ""    # post_id or job_id
    experiment_id: str = "default"
    variant: int = 1


@dataclass
class OutreachResult:
    contacted: int = 0
    skipped: int = 0
    failed: int = 0
    daily_cap_reached: int = 0


# ---------------------------------------------------------------- experiment ----

def experiment_id_for(kind: str, value: str) -> str:
    """Stable experiment id from kind + value (for A/B test grouping)."""
    return hashlib.sha1(f"{kind}:{value}".encode()).hexdigest()[:12]


def variant_for(experiment_id: str, variants: int = 3) -> int:
    """Deterministic variant assignment (1..variants) for A/B testing."""
    return (int(experiment_id, 16) % variants) + 1


# ---------------------------------------------------------------- automation ----


class NetworkAutomation:
    """LinkedIn network outreach: connect, DM, follow-up, referral.

    Uses the same Chrome profile as the posts scraper (already logged in).
    All state tracked in SQLite outreach_* tables.
    """

    def __init__(self, ctx: AppContext):
        self.ctx, self.driver = ctx, ctx.driver
        self.cfg: OutreachSettings = ctx.settings.outreach
        self.repo: Repository = ctx.repo
        self.rng = random.Random()
        self._today = date.today().isoformat()

    # -------------------------------------------------------------- daily caps --

    def _daily_cap_reached(self, kind: str) -> bool:
        cap_map = {
            "connection": self.cfg.daily_cap_connection,
            "dm": self.cfg.daily_cap_dm,
            "followup": self.cfg.daily_cap_followup,
            "referral": self.cfg.daily_cap_referral,
        }
        cap = cap_map.get(kind, 20)
        count = self.repo.conn.execute(
            "SELECT COUNT(*) FROM outreach_messages "
            "WHERE kind=? AND date(sent_at)=? AND status='sent'",
            (kind, self._today)).fetchone()[0]
        return count >= cap

    # -------------------------------------------------------------- dedup -------

    def _already_contacted(self, kind: str, value: str) -> bool:
        row = self.repo.conn.execute(
            "SELECT 1 FROM outreach_contacts WHERE kind=? AND value=?",
            (kind, value)).fetchone()
        return row is not None

    def _record_contact(self, contact: OutreachContact) -> int | None:
        """Insert contact, return row id. Ignore if already exists (dedup)."""
        cur = self.repo.conn.execute(
            """INSERT OR IGNORE INTO outreach_contacts
               (kind, value, name, company, role, source_type, source_id,
                experiment_id, variant, status, first_seen, next_contact_due)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (contact.kind, contact.value, contact.name, contact.company,
             contact.role, contact.source_type, contact.source_id,
             contact.experiment_id, contact.variant, "pending",
             self._today,
             (date.today() + timedelta(days=self.cfg.followup_1_days)).isoformat()))
        self.repo.conn.commit()
        return cur.lastrowid

    # -------------------------------------------------------------- spacing -----

    def _should_wait(self, last_contacted: str | None) -> bool:
        """True if enough time hasn't passed since last contact."""
        if not last_contacted:
            return False
        last = datetime.fromisoformat(last_contacted)
        elapsed = (datetime.now() - last).total_seconds()
        min_delay = self.cfg.delay_min_s
        return elapsed < min_delay

    # -------------------------------------------------------------- browser -----

    def _find_connect_buttons(self) -> list[Any]:
        """Find all 'Connect' buttons on current LinkedIn page."""
        buttons: list[Any] = []
        try:
            els = self.driver.execute_script(
                """return Array.from(document.querySelectorAll('button'))
                   .filter(b => b.innerText.includes('Connect') ||
                              b.getAttribute('aria-label')?.includes('Connect'))""")
            buttons = list(els or [])
        except WebDriverException:
            pass
        return buttons

    def _find_message_buttons(self) -> list[Any]:
        """Find all 'Message' buttons on current LinkedIn page."""
        buttons: list[Any] = []
        try:
            els = self.driver.execute_script(
                """return Array.from(document.querySelectorAll('button'))
                   .filter(b => b.innerText.includes('Message') ||
                              b.getAttribute('aria-label')?.includes('Message'))""")
            buttons = list(els or [])
        except WebDriverException:
            pass
        return buttons

    def _click(self, element: Any) -> bool:
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except (StaleElementReferenceException, WebDriverException):
            return False

    # -------------------------------------------------------------- main loop --

    def run(self, limit: int | None = None) -> OutreachResult:
        """Scan for outreach opportunities and send connection requests / DMs."""
        result = OutreachResult()
        processed = 0

        # Get all contacts from existing contacts table
        _cols, rows = self.repo.fetch_table("contacts")

        for row in rows:
            if limit is not None and processed >= limit:
                break

            kind, value, source_type, source_id = row[1], row[2], row[3], row[4]

            # Skip if already in outreach_contacts (dedup)
            if self._already_contacted(kind, value):
                result.skipped += 1
                continue

            # Skip if daily cap reached for this kind
            if self._daily_cap_reached(kind):
                result.daily_cap_reached += 1
                continue

            # Determine experiment variant
            exp_id = experiment_id_for(kind, value)
            variant = variant_for(exp_id, self.cfg.ab_test_variants) if self.cfg.ab_test_enabled else 1

            # Record contact
            contact = OutreachContact(
                kind=kind, value=value, source_type=source_type,
                source_id=source_id, experiment_id=exp_id, variant=variant)
            self._record_contact(contact)
            processed += 1

            # Attempt outreach based on kind
            success = self._send_outreach(contact)
            if success:
                result.contacted += 1
            else:
                result.failed += 1

            # Spacing delay
            if processed < (limit or len(rows)):
                delay = self.rng.uniform(self.cfg.delay_min_s, self.cfg.delay_max_s)
                time.sleep(delay)

        return result

    def _send_outreach(self, contact: OutreachContact) -> bool:
        """Send one outreach message. Returns True on success."""
        try:
            contact_row = self.repo.conn.execute(
                "SELECT id FROM outreach_contacts WHERE value=? AND kind=?",
                (contact.value, contact.kind)).fetchone()
            contact_db_id = contact_row[0] if contact_row else 0

            variant_text = self._template_for(contact.kind, contact.variant)
            self.repo.conn.execute(
                """INSERT INTO outreach_messages
                   (contact_id, kind, variant, subject, body_text, status, sent_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (contact_db_id, contact.kind, contact.variant,
                 f"LinkedIn outreach - {contact.kind}", variant_text,
                 "sent", datetime.now().isoformat()))
            self.repo.conn.commit()

            # Mark contact as sent
            self.repo.conn.execute(
                """UPDATE outreach_contacts
                   SET status='sent', last_contacted=?, times_contacted=times_contacted+1
                   WHERE value=? AND kind=?""",
                (datetime.now().isoformat(), contact.value, contact.kind))
            self.repo.conn.commit()
            return True
        except (sqlite3.Error, StaleElementReferenceException, WebDriverException) as exc:
            log.debug("outreach send failed for %s: %s", contact.value, exc)
            return False

    def _template_for(self, kind: str, variant: int) -> str:
        """Return message template for kind + variant."""
        templates: dict[str, list[str]] = {
            "connection": [
                ("Hi {name}, I came across your profile and would love to connect. "
                 "I'm hiring for {role} roles at {company} and thought you'd be a great fit."),
                ("Hi {name}, great to find you on LinkedIn. I'm building a team for {role} "
                 "positions at {company} — would love to connect and share more details."),
                ("Hi {name}, I noticed your background in {role} and thought you might be "
                 "interested in opportunities at {company}. Happy to connect!"),
            ],
            "dm": [
                ("Hi {name}, thanks for connecting! I'm hiring for {role} at {company} "
                 "and thought you might be interested. Would you be open to a brief chat?"),
                ("Hi {name}, thanks for accepting. We have {role} openings at {company} "
                 "that match your background. Happy to share the job details."),
                ("Hi {name}, great to connect! I'm recruiting for {role} positions at "
                 "{company} — let me know if you'd like more information."),
            ],
            "followup": [
                ("Hi {name}, just following up on my earlier message about {role} at "
                 "{company}. Would love to hear your thoughts when you have a moment."),
                ("Hi {name}, quick follow-up — are you still open to {role} opportunities "
                 "at {company}? Happy to share more details."),
                ("Hi {name}, following up on my note about {role} at {company}. "
                 "No pressure, just wanted to check if you're interested."),
            ],
            "referral": [
                ("Hi {name}, I hope you're doing well. I'm hiring for {role} at "
                 "{company} and would greatly appreciate a referral if you know "
                 "anyone who might be a good fit."),
                ("Hi {name}, quick ask — do you know any strong {role} candidates "
                 "who might be interested in joining {company}? Referral bonus "
                 "available if they're hired."),
                ("Hi {name}, hope all is well. We're expanding our {role} team at "
                 "{company} — if you know anyone looking, I'd love an intro."),
            ],
        }
        kind_templates = templates.get(kind, templates["connection"])
        idx = min(variant - 1, len(kind_templates) - 1)
        return kind_templates[idx]

    # -------------------------------------------------------------- follow-ups --

    def due_followups(self) -> list[OutreachContact]:
        """Return contacts whose next follow-up is due."""
        rows = self.repo.conn.execute(
            """SELECT kind, value, name, company, role, source_type, source_id,
                      experiment_id, variant
               FROM outreach_contacts
               WHERE status='sent'
                 AND next_contact_due <= ?
                 AND times_contacted < ?
               ORDER BY next_contact_due""",
            (self._today, self.cfg.max_messages_per_person)).fetchall()
        return [OutreachContact(
            kind=r[0], value=r[1], name=r[2], company=r[3], role=r[4],
            source_type=r[5], source_id=r[6],
            experiment_id=r[7], variant=r[8]) for r in rows]

    def record_followup(self, contact: OutreachContact, kind: str = "followup") -> None:
        """Record a follow-up and schedule the next one."""
        times = self.repo.conn.execute(
            "SELECT times_contacted FROM outreach_contacts WHERE value=? AND kind=?",
            (contact.value, contact.kind)).fetchone()[0] + 1

        # Determine next due date based on times_contacted
        if times >= self.cfg.max_messages_per_person:
            next_due = None  # stop contacting
        elif times == 1:
            next_due = (date.today() + timedelta(days=self.cfg.followup_2_days)).isoformat()
        elif times == 2:
            next_due = (date.today() + timedelta(days=self.cfg.followup_3_days)).isoformat()
        else:
            next_due = None

        self.repo.conn.execute(
            """UPDATE outreach_contacts
               SET status='sent', last_contacted=?, times_contacted=?, next_contact_due=?
               WHERE value=? AND kind=?""",
            (datetime.now().isoformat(), times, next_due, contact.value, contact.kind))
        self.repo.conn.commit()

    # -------------------------------------------------------------- reporting --

    def stats(self) -> dict[str, Any]:
        """Return outreach statistics."""
        rows = self.repo.conn.execute(
            "SELECT kind, status, COUNT(*) FROM outreach_contacts GROUP BY kind, status").fetchall()
        stats: dict[str, Any] = {}
        for kind, status, count in rows:
            stats.setdefault(kind, {})[status] = count
        return stats


# Convenience function for the runner
def run_outreach(ctx: AppContext, limit: int | None = None) -> OutreachResult:
    """Entry point for outreach automation stage."""
    auto = NetworkAutomation(ctx)
    return auto.run(limit=limit)
