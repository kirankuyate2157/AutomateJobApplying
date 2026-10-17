import smtplib
import tempfile
import unittest
from pathlib import Path

from jobpilot.features.outreach.drafts import draft_from_contacts
from jobpilot.features.outreach.mailer import Mailer
from jobpilot.features.outreach.templates import compose_application, greeting_for
from jobpilot.profile.profile import Profile
from jobpilot.settings import MailSettings, Settings
from jobpilot.storage.db import Repository
import os


def profile(**kw):
    base = dict(first_name="Kiran", last_name="K", email="me@x.com", phone="9000000000", total_years=3,
                headline="Full Stack Developer", skills={"python": 3, "node.js": 3}, target_roles=["Python Developer"],
                projects=["Built a thing <b>"], github_url="https://github.com/me")
    base.update(kw)
    return Profile.from_dict(base)


class TemplateTests(unittest.TestCase):
    def test_greeting(self):
        self.assertEqual(greeting_for("rahul.sharma@x.com"), "Hi Rahul,")
        self.assertEqual(greeting_for("hr@x.com"), "Hello Hiring Team,")
        self.assertEqual(greeting_for("careers@x.com"), "Hello Hiring Team,")
        self.assertEqual(greeting_for("a1b2@x.com"), "Hello Hiring Team,")

    def test_compose_escapes_html_and_fills(self):
        subject, text, page = compose_application(profile(), "priya@firm.com", "Python Developer")
        self.assertEqual(subject, "Application for Python Developer | 3 YOE | Kiran K")
        self.assertIn("Hi Priya,", text)
        self.assertIn("python, node.js", text)
        self.assertIn("&lt;b&gt;", page)                 # project text must not inject HTML
        self.assertNotIn("$", text)                      # every placeholder substituted

    def test_custom_template_file_wins(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "application_email.txt").write_text("Hey $first_name for $role", encoding="utf-8")
            _s, text, _h = compose_application(profile(), "a@b.com", "SDE", Path(d))
            self.assertEqual(text, "Hey Kiran for SDE")


class DraftTests(unittest.TestCase):
    def test_only_relevant_hiring_contacts_drafted(self):
        repo, s, p = Repository(":memory:"), Settings(), profile()
        repo.add_post("p1", "", "", "Hiring Python Developer. Mail CV", "", "k", True, 4, ["Python Developer"])
        repo.add_post("p2", "", "", "Hiring accountants for finance team", "", "k", True, 4, [])
        repo.add_post("p3", "", "", "python python python", "", "k", False, 0, [])
        for pid, mail in (("p1", "talent@good.com"), ("p2", "hr@acct.com"), ("p3", "x@seeker.com")):
            repo.add_contact("email", mail, "post", pid)
        repo.add_contact("email", "me@x.com", "post", "p1")            # own address never mailed
        self.assertEqual(draft_from_contacts(repo, p, s), 1)
        rows = repo.mail_batch(["pending"], 10)
        self.assertEqual([r["to_email"] for r in rows], ["talent@good.com"])
        self.assertEqual(draft_from_contacts(repo, p, s), 0)           # idempotent

    def test_auto_send_marks_approved(self):
        repo, s = Repository(":memory:"), Settings()
        s.mail.auto_send = True
        repo.add_post("p1", "", "", "Hiring Python Developer", "", "k", True, 4, [])
        repo.add_contact("email", "talent@good.com", "post", "p1")
        draft_from_contacts(repo, profile(), s)
        self.assertEqual(len(repo.mail_batch(["approved"], 5)), 1)


class FakeSMTP:
    sent, fail_for = [], set()
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, u, p): pass
    def send_message(self, msg):
        if msg["To"] in self.fail_for:
            raise smtplib.SMTPRecipientsRefused({})
        self.sent.append(msg["To"])


class MailerTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.sent, FakeSMTP.fail_for = [], set()
        os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"] = "u@x.com", "pw"

    def queue(self, repo, *emails):
        for e in emails:
            repo.queue_mail(e, "subj", "body", "<p>body</p>", "", "post", "p", "approved")

    def test_send_caps_and_failures(self):
        repo = Repository(":memory:")
        self.queue(repo, "a@one.com", "b@two.com", "c@three.com", "d@one.com")
        FakeSMTP.fail_for = {"b@two.com"}
        cfg = MailSettings(daily_cap=10, max_per_domain_per_day=1)
        counts = Mailer(cfg, repo, profile(), FakeSMTP, sleep=lambda _x: None).send_approved()
        self.assertEqual(counts, {"sent": 2, "failed": 1, "skipped": 1})      # d@one.com hit the domain cap
        self.assertEqual(FakeSMTP.sent, ["a@one.com", "c@three.com"])
        self.assertEqual(repo.count_mail_sent_today(), 2)

    def test_daily_cap(self):
        repo = Repository(":memory:")
        self.queue(repo, "a@one.com", "b@two.com", "c@three.com")
        cfg = MailSettings(daily_cap=2)
        counts = Mailer(cfg, repo, profile(), FakeSMTP, sleep=lambda _x: None).send_approved()
        self.assertEqual(counts["sent"], 2)

    def test_no_credentials_sends_nothing(self):
        os.environ.pop("SMTP_USER"); os.environ.pop("SMTP_APP_PASSWORD")
        repo = Repository(":memory:")
        self.queue(repo, "a@one.com")
        counts = Mailer(MailSettings(), repo, profile(), FakeSMTP, sleep=lambda _x: None).send_approved()
        self.assertEqual(counts["sent"], 0)
        self.assertEqual(FakeSMTP.sent, [])


if __name__ == "__main__":
    unittest.main()
