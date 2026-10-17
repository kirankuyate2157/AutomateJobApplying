import csv
import tempfile
import unittest
from pathlib import Path

from jobpilot.storage.db import Repository
from jobpilot.storage.legacy_import import import_legacy_csv

HEADER = ["Job ID", "Title", "Company", "Date Applied", "Job Link", "External Job link", "Questions Found"]
QUESTIONS = repr({
    ("Have you completed Bachelor's Degree? [  \"Yes\"<Yes>, \"No\"<No>, ]", '"Yes"<Yes>', "radio", '"Yes"<Yes>'),
    ("Phone country code [ \"List of phone country codes\" ]", "Yes", "select", "India (+91)"),
    ("how many years of work experience do you have with ios?", "0", "text", "0"),
})


class LegacyImportTests(unittest.TestCase):
    def test_import(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "old.csv"
            with open(p, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(HEADER)
                w.writerow(["111", "Dev", "Acme", "2026-10-07 07:00:00", "u", "Easy Applied", QUESTIONS])
                w.writerow(["222", "Dev2", "Beta", "Pending", "u2", "https://ext.example/apply", ""])
            repo = Repository(":memory:")
            rep = import_legacy_csv(repo, p)
            self.assertEqual((rep.jobs, rep.questions), (2, 2))
            self.assertEqual(repo.job_status("111"), "applied")
            self.assertEqual(repo.job_status("222"), "external")
            self.assertTrue(repo.job_is_final("111", dry_run=False))
            q = repo.get_question("have you completed bachelor s degree")
            self.assertEqual((q["answer"], q["status"]), ("Yes", "legacy"))
            self.assertIsNone(repo.get_question("phone country code"))      # rules handle it
            # idempotent
            again = import_legacy_csv(repo, p)
            self.assertEqual((again.jobs, again.questions), (0, 0))


class RealFileSmoke(unittest.TestCase):
    """Runs only if the real legacy export is mounted (as in the dev sandbox)."""
    PATH = Path("/mnt/project/all_applied_applications_history.csv")

    @unittest.skipUnless(PATH.exists(), "real legacy csv not present")
    def test_real_file(self):
        repo = Repository(":memory:")
        rep = import_legacy_csv(repo, self.PATH)
        self.assertGreater(rep.jobs, 50)
        self.assertGreater(rep.questions, 5)


if __name__ == "__main__":
    unittest.main()
