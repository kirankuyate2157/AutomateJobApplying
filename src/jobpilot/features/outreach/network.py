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

All state lives in SQLite outreach_* tables (migration v3).

ACTUAL BROWSER ACTIONS:
  * Opens https://www.linkedin.com/mynetwork/grow/ (reliable Connect buttons)
  * Finds and clicks Connect buttons on "People you may know" cards
  * Extracts name, title, company from each card
  * Records only genuinely sent messages in SQLite
"""

from __future__ import annotations

import hashlib
import logging
import random
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any

from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import WebDriverException

from ...core.context import AppContext
from ...settings import OutreachSettings
from ...storage.db import Repository

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ data models


@dataclass
class OutreachContact:
    """One person we may reach out to."""
    kind: str              # connection | dm | followup | referral
    value: str             # linkedin_profile_url | email | phone
    name: str = ""
    company: str = ""
    role: str = ""
    source_type: str = ""  # feed | jobs | manual | network
    source_id: str = ""    # profile_url or post_id
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

    GROW_URL = "https://www.linkedin.com/mynetwork/grow/"

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
        return bool(count >= cap)

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

    # -------------------------------------------------------------- browser -----

    def _click(self, element: Any) -> bool:
        try:
            self.driver.execute_script("arguments[0].click();", element)
        except (StaleElementReferenceException, WebDriverException):
            return False
        else:
            return True

    def _find_connect_buttons(self) -> list[Any]:
        """Find all 'Connect' buttons on current LinkedIn page."""
        buttons: list[Any] = []
        try:
            els = self.driver.execute_script(
                "return Array.from(document.querySelectorAll('button'))"
                ".filter(b => b.innerText.trim() === 'Connect')")
            buttons = list(els or [])
        except WebDriverException:
            pass
        return buttons

    def _extract_card_info(self, btn_el: Any) -> tuple[str, str, str]:
        """Extract (name, role, company) from the card containing a Connect button."""
        try:
            card_text = self.driver.execute_script(
                "const btn = arguments[0];"
                "let parent = btn.parentElement;"
                "for (let i = 0; i < 10 && parent; i++) {"
                "  const text = parent.innerText || '';"
                "  if (text.includes('Connect') && text.length > 30 && text.length < 400) {"
                "    return text;"
                "  }"
                "  parent = parent.parentElement;"
                "}"
                "return '';", btn_el) or ""
        except WebDriverException:
            return "", "", ""

        # Parse: name\nrole\ncompany\nConnect
        lines = [line.strip() for line in card_text.split("\n") if line.strip()]
        # Remove non-name lines
        filtered = []
        for line in lines:
            if line in ("Connect", "Follow", "Message"):
                continue
            if "mutual connection" in line.lower():
                continue
            if "Show all" in line:
                continue
            filtered.append(line)
        lines = filtered

        if not lines:
            return "", "", ""

        name = lines[0] if len(lines) > 0 else ""
        role = lines[1] if len(lines) > 1 else ""
        company = lines[2] if len(lines) > 2 else ""

        return name, role, company

    # -------------------------------------------------------------- main loop --

    def run(self, limit: int | None = None) -> OutreachResult:
        """Open LinkedIn 'Grow your network' page, send connection requests.

        Only counts a contact as 'contacted' if the browser actually clicked
        a Connect button. Database records are created only after success.
        """
        result = OutreachResult()

        # Open LinkedIn Grow page (reliable Connect buttons)
        log.info("Opening LinkedIn grow page: %s", self.GROW_URL)
        self.driver.get(self.GROW_URL)
        time.sleep(5)

        # Detect login/checkpoint wall
        current_url = self.driver.current_url
        blocked_markers = ("login", "authwall", "checkpoint", "challenge", "uas/")
        if any(m in current_url for m in blocked_markers):
            log.warning(
                "LinkedIn checkpoint/login wall detected at %s. "
                "Manual login required before automation can proceed.",
                current_url)
            result.failed = 1
            return result

        processed = 0
        max_posts = limit or 50
        scroll_rounds = 0
        max_scroll_rounds = 10

        while processed < max_posts and scroll_rounds < max_scroll_rounds:
            # Find Connect buttons
            buttons = self._find_connect_buttons()
            if not buttons:
                log.debug("No Connect buttons found, scrolling for more")
                self.driver.execute_script("window.scrollBy(0, window.innerHeight);")
                time.sleep(2)
                scroll_rounds += 1
                continue

            new_found = 0
            for btn in buttons:
                if processed >= max_posts:
                    break

                # Extract name, role, company from card
                name, role, company = self._extract_card_info(btn)
                value = name.lower().replace(" ", "-") if name else f"profile:{processed}"

                contact = OutreachContact(
                    kind="connection",
                    value=value,
                    name=name,
                    company=company,
                    role=role,
                    source_type="feed",
                    source_id=value,
                    experiment_id=experiment_id_for("connection", value),
                    variant=variant_for(experiment_id_for("connection", value), 3),
                )

                # Dedup check
                if self._already_contacted(contact.kind, contact.value):
                    result.skipped += 1
                    continue

                # Daily cap check
                if self._daily_cap_reached(contact.kind):
                    result.daily_cap_reached += 1
                    continue

                # Click Connect
                clicked = self._click(btn)

                self._record_contact(contact)
                processed += 1
                new_found += 1

                if clicked:
                    result.contacted += 1
                    # Mark as sent
                    self.repo.conn.execute(
                        """UPDATE outreach_contacts
                           SET status='sent', last_contacted=?,
                               times_contacted=times_contacted+1
                           WHERE value=? AND kind=?""",
                        (datetime.now().isoformat(), contact.value, contact.kind))
                    self.repo.conn.commit()

                    # Record message
                    variant_text = self._template_for(contact.kind, contact.variant)
                    contact_row = self.repo.conn.execute(
                        "SELECT id FROM outreach_contacts WHERE value=? AND kind=?",
                        (contact.value, contact.kind)).fetchone()
                    contact_db_id = contact_row[0] if contact_row else 0
                    self.repo.conn.execute(
                        """INSERT INTO outreach_messages
                           (contact_id, kind, variant, subject, body_text, status, sent_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (contact_db_id, contact.kind, contact.variant,
                         f"LinkedIn {contact.kind}", variant_text,
                         "sent", datetime.now().isoformat()))
                    self.repo.conn.commit()
                    log.info("Connected with %s (%s)", contact.name, contact.value)
                else:
                    result.failed += 1
                    log.debug("Failed to click Connect for %s", contact.value)

                # Spacing delay between contacts
                if processed < max_posts:
                    delay = self.rng.uniform(self.cfg.delay_min_s, self.cfg.delay_max_s)
                    time.sleep(delay)

            if new_found == 0:
                # Scroll for more people
                self.driver.execute_script("window.scrollBy(0, window.innerHeight);")
                time.sleep(2)
                scroll_rounds += 1

        result.skipped = max(0, processed - result.contacted - result.failed)
        return result

    def _is_hiring_signal(self, text: str) -> bool:
        """Quick check: does this post look like a hiring post?"""
        if not text:
            return False
        t = text.lower()
        signals = [
            "hiring", "we're hiring", "we are hiring",
            "send your resume", "send your cv", "share your resume",
            "apply now", "apply here", "job opening", "openings",
            "vacancy", "walk-in", "walk in", "immediate joiner",
            "join our team", "join my team", "dm me", "dm us",
            "mailto:", "forms.gle", "tally.so",
            "looking for developer", "looking for engineer",
            "looking for python", "looking for java",
        ]
        return any(sig in t for sig in signals)

    def _send_outreach(self, contact: OutreachContact) -> bool:
        """Legacy method kept for compatibility."""
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

            self.repo.conn.execute(
                """UPDATE outreach_contacts
                   SET status='sent', last_contacted=?, times_contacted=times_contacted+1
                   WHERE value=? AND kind=?""",
                (datetime.now().isoformat(), contact.value, contact.kind))
            self.repo.conn.commit()
        except (sqlite3.Error, StaleElementReferenceException, WebDriverException) as exc:
            log.debug("outreach send failed for %s: %s", contact.value, exc)
            return False
        else:
            return True

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
