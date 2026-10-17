"""SMTP sender with safety rails.

Replaces the legacy approach (POSTing to a third-party Render URL): mail now
leaves from YOUR account via SMTP using an app password, with
  * a daily cap and a per-domain cap (avoid looking like spam)
  * randomised delays between sends
  * every outcome stored in mail_queue (sent / failed + error text)
"""
from __future__ import annotations

import logging
import random
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from ...profile.profile import Profile
from ...settings import MailSettings, env
from ...storage.db import Repository

log = logging.getLogger(__name__)


def build_message(profile: Profile, row, sender: str, attach_resume: bool) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{profile.full_name} <{sender}>"
    msg["To"] = row["to_email"]
    msg["Reply-To"] = profile.email
    msg["Subject"] = row["subject"]
    msg.set_content(row["body_text"])
    msg.add_alternative(row["body_html"], subtype="html")
    path = Path(row["resume_path"]) if row["resume_path"] else None
    if attach_resume and path and path.exists():
        msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)
    return msg


class Mailer:
    def __init__(self, cfg: MailSettings, repo: Repository, profile: Profile,
                 smtp_factory: Callable[..., smtplib.SMTP] | None = None,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
        self.cfg, self.repo, self.profile = cfg, repo, profile
        self.smtp_factory = smtp_factory or (lambda host, port: smtplib.SMTP_SSL(host, port, timeout=30))
        self.sleep, self.rng = sleep, rng or random.Random()

    def send_approved(self, limit: int | None = None) -> dict[str, int]:
        counts = {"sent": 0, "failed": 0, "skipped": 0}
        user, password = env(self.cfg.user_env), env(self.cfg.password_env)
        if not user or not password:
            log.error("SMTP credentials missing (%s / %s in .env): nothing sent", self.cfg.user_env, self.cfg.password_env)
            return counts
        budget = self.cfg.daily_cap - self.repo.count_mail_sent_today()
        if limit is not None:
            budget = min(budget, limit)
        if budget <= 0:
            log.info("mail daily cap reached")
            return counts
        rows = self.repo.mail_batch(["approved"], budget)
        if not rows:
            return counts
        with self.smtp_factory(self.cfg.smtp_host, self.cfg.smtp_port) as smtp:
            smtp.login(user, password)
            for i, row in enumerate(rows):
                domain = row["to_email"].split("@", 1)[1]
                if self.repo.count_mail_to_domain_today(domain) >= self.cfg.max_per_domain_per_day:
                    self.repo.mark_mail(row["id"], "skipped", "per-domain daily cap")
                    counts["skipped"] += 1
                    continue
                try:
                    smtp.send_message(build_message(self.profile, row, user, self.cfg.attach_resume))
                    self.repo.mark_mail(row["id"], "sent")
                    counts["sent"] += 1
                    log.info("sent application to %s", row["to_email"])
                except (smtplib.SMTPException, OSError) as exc:
                    self.repo.mark_mail(row["id"], "failed", str(exc)[:300])
                    counts["failed"] += 1
                    log.warning("send to %s failed: %s", row["to_email"], exc)
                if i < len(rows) - 1:
                    self.sleep(self.rng.uniform(self.cfg.delay_min_s, self.cfg.delay_max_s))
        return counts
