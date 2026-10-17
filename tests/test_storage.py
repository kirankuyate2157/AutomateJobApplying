import unittest
from datetime import datetime

from jobpilot.domain.models import Job
from jobpilot.storage.db import Repository


def job(i="1", **kw):
    return Job(job_id=i, title="Backend Developer", company="Acme", location="Pune, India", **kw)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")

    def test_upsert_keeps_status(self):
        self.repo.upsert_job(job())
        self.repo.set_job_status("1", "applied")
        self.repo.upsert_job(job(description="new text"))       # re-scrape must not reset status
        self.assertEqual(self.repo.job_status("1"), "applied")

    def test_final_semantics(self):
        self.repo.upsert_job(job())
        self.assertFalse(self.repo.job_is_final("1", dry_run=False))
        self.repo.set_job_status("1", "dry_run_ok")
        self.assertTrue(self.repo.job_is_final("1", dry_run=True))
        self.assertFalse(self.repo.job_is_final("1", dry_run=False))   # eligible once live
        self.repo.set_job_status("1", "needs_review")
        self.assertFalse(self.repo.job_is_final("1", dry_run=True))
        self.repo.set_job_status("1", "applied")
        self.assertTrue(self.repo.job_is_final("1", dry_run=False))

    def test_applied_today_counts(self):
        for i in "123":
            self.repo.upsert_job(job(i))
        self.repo.set_job_status("1", "applied")
        self.repo.set_job_status("2", "applied")
        self.repo.set_job_status("3", "skipped")
        self.assertEqual(self.repo.count_applied_today(), 2)

    def test_question_precedence(self):
        self.repo.record_question("k", "Q?", "text", [], None, "", 0, "pending")
        self.assertTrue(self.repo.set_user_answer("k", "42"))
        # later auto answers must not clobber the user's answer
        self.repo.record_question("k", "Q?", "text", [], "7", "rule:x", 0.9, "auto")
        q = self.repo.get_question("k")
        self.assertEqual((q["answer"], q["status"], q["times_seen"]), ("42", "user", 2))

    def test_legacy_kept_while_pending(self):
        self.repo.record_question("k", "Q?", "text", [], "old", "legacy", 0.5, "legacy")
        self.repo.record_question("k", "Q?", "text", [], None, "", 0, "pending")
        self.assertEqual(self.repo.get_question("k")["status"], "legacy")
        self.assertEqual(self.repo.promote_legacy(), 1)
        self.assertEqual(self.repo.get_question("k")["status"], "user")

    def test_contacts_and_mail_dedupe(self):
        self.assertTrue(self.repo.add_contact("email", "a@b.com", "post", "p1"))
        self.assertFalse(self.repo.add_contact("email", "a@b.com", "post", "p2"))
        self.assertTrue(self.repo.queue_mail("a@b.com", "s", "t", "h", "", "post", "p1"))
        self.assertFalse(self.repo.queue_mail("a@b.com", "s", "t", "h", "", "post", "p2"))
        self.assertEqual(self.repo.approve_pending_mail(), 1)
        self.assertEqual(len(self.repo.mail_batch(["approved"], 10)), 1)

    def test_search_stats_accumulate(self):
        self.repo.record_search("q", 10, 2)
        self.repo.record_search("q", 5, 1)
        self.assertEqual(self.repo.search_stats()["q"], (15, 3, 2))

    def test_export_whitelist(self):
        with self.assertRaises(ValueError):
            self.repo.fetch_table("sqlite_master")


if __name__ == "__main__":
    unittest.main()
