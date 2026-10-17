import random
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from jobpilot.domain.models import ApplyResult, Job, Post
from jobpilot.exceptions import DailyLimitReached
from jobpilot.features.jobs.runner import DailyRunner
from jobpilot.features.jobs.throttle import HourlyThrottle
from jobpilot.features.posts.runner import run_posts
from jobpilot.profile.profile import Profile
from jobpilot.search.strategy import QueryPlanner
from jobpilot.settings import PostSettings, Settings
from jobpilot.storage.db import Repository


def profile():
    return Profile.from_dict(dict(
        first_name="A", last_name="B", email="a@b.c", phone="9000000000", total_years=3,
        skills={"python": 3, "docker": 2, "aws": 1}, target_roles=["Python Developer"],
        avoid_keywords=["php"], max_required_years=4))


def make_job(i, title="Python Developer", desc="3 years experience. Python Docker AWS.", **kw):
    return Job(job_id=str(i), title=title, company=f"Co{i}", location="Pune, India",
               description=desc, posted_at=datetime.now() - timedelta(hours=1), **kw)


class FakeSource:
    def __init__(self, jobs): self.jobs, self.calls = jobs, 0
    def iter_jobs(self, spec):
        self.calls += 1
        yield from (self.jobs if spec.pass_no == 1 else [])


class FakeApplier:
    def __init__(self, status="applied", fail_with=None): self.status, self.fail, self.applied = status, fail_with, []
    def apply(self, job, resume_path=""):
        if self.fail and len(self.applied) >= 2:
            raise self.fail
        self.applied.append(job.job_id)
        return ApplyResult(self.status)


def runner(jobs, applier, dry_run=False, target=30, repo=None, min_score=50):
    s = Settings()
    s.apply.daily_target, s.apply.min_score = target, min_score
    s.search.locations = ["India"]
    repo = repo or Repository(":memory:")
    planner = QueryPlanner(profile(), s.search, repo, rng=random.Random(0))
    return DailyRunner(repo, profile(), s, planner, FakeSource(jobs), applier, dry_run,
                       sleep=lambda _x: None), repo


class JobsRunnerTests(unittest.TestCase):
    def test_stops_at_quota_and_records(self):
        jobs = [make_job(i) for i in range(10)]
        r, repo = runner(jobs, FakeApplier(), target=3)
        s = r.run()
        self.assertEqual((s.applied, s.seen >= 3), (3, True))
        self.assertEqual(repo.count_applied_today(), 3)

    def test_existing_applications_reduce_quota(self):
        r, repo = runner([make_job(i) for i in range(10, 20)], FakeApplier(), target=3)
        for i in range(2):
            repo.import_applied(str(i), "t", "c", "u", datetime.now().isoformat(), "applied")
        self.assertEqual(r.run().applied, 1)

    def test_skips_bad_jobs_without_applying(self):
        jobs = [make_job(1, desc="PHP developer, 3 years experience"),
                make_job(2, title="Sales Manager", desc="sell. 3 years experience"),
                make_job(3)]
        applier = FakeApplier()
        r, repo = runner(jobs, applier)
        s = r.run()
        self.assertEqual(applier.applied, ["3"])
        self.assertEqual(s.skipped, 2)
        self.assertEqual(repo.job_status("1"), "skipped")

    def test_dedupe_between_runs_and_dry_run_semantics(self):
        jobs = [make_job(1)]
        r, repo = runner(jobs, FakeApplier("dry_run_ok"), dry_run=True)
        self.assertEqual(r.run().dry_run_ok, 1)
        r2, _ = runner(jobs, FakeApplier("dry_run_ok"), dry_run=True, repo=repo)
        self.assertEqual(r2.run().dry_run_ok, 0)               # not repeated in another dry run
        live_applier = FakeApplier()
        r3, _ = runner(jobs, live_applier, dry_run=False, repo=repo)
        self.assertEqual(r3.run().applied, 1)                  # but eligible once live

    def test_needs_review_is_retried_next_run(self):
        jobs = [make_job(1)]
        r, repo = runner(jobs, FakeApplier("needs_review"))
        self.assertEqual(r.run().needs_review, 1)
        r2, _ = runner(jobs, FakeApplier("applied"), repo=repo)
        self.assertEqual(r2.run().applied, 1)

    def test_daily_limit_stops_run_cleanly(self):
        jobs = [make_job(i) for i in range(6)]
        r, repo = runner(jobs, FakeApplier(fail_with=DailyLimitReached("limit")))
        s = r.run()
        self.assertEqual(s.applied, 2)
        self.assertIn("limit", s.stopped)
        self.assertEqual(repo.count("runs"), 1)

    def test_contacts_harvested_from_descriptions(self):
        jobs = [make_job(1, desc="Python 3 years experience. Mail CV to talent@acme.io or call 9876543210")]
        r, repo = runner(jobs, FakeApplier())
        r.run()
        values = {row[2] for row in repo.fetch_table("contacts")[1]}
        self.assertIn("talent@acme.io", values)
        self.assertIn("+919876543210", values)

    def test_search_stats_updated(self):
        r, repo = runner([make_job(1)], FakeApplier())
        r.run()
        self.assertTrue(any(v[1] == 1 for v in repo.search_stats().values()))


class ThrottleTests(unittest.TestCase):
    def test_blocks_when_window_full(self):
        t = [0.0]
        slept = []
        th = HourlyThrottle(2, clock=lambda: t[0], sleep=slept.append)
        th.mark(); t[0] = 10; th.mark(); t[0] = 20
        self.assertGreater(th.wait(), 3000)
        t[0] = 4000
        self.assertEqual(th.wait(), 0.0)


class FakePosts:
    def __init__(self, posts): self.posts = posts
    def iter_posts(self, keyword): yield from self.posts


class PostsTests(unittest.TestCase):
    def test_posts_pipeline(self):
        posts = [
            Post("p1", text="We are hiring Python Developers! Send your resume to talent@foo.com or call +91 98765 43210"),
            Post("p2", text="I am looking for new opportunities #OpenToWork reach me me@x.com"),
            Post("p3", text="Hiring Node dev. Apply: https://forms.gle/abc", hrefs=["mailto:cv@bar.in"]),
        ]
        repo = Repository(":memory:")
        cfg = PostSettings(keywords=["k1", "k2"])               # same posts returned for both keywords
        s = run_posts(repo, FakePosts(posts), cfg)
        self.assertEqual((s.scanned, s.hiring, s.duplicates), (3, 2, 3))
        kinds = {(r[1], r[2]) for r in repo.fetch_table("contacts")[1]}
        self.assertIn(("email", "talent@foo.com"), kinds)
        self.assertIn(("email", "cv@bar.in"), kinds)
        self.assertIn(("form", "https://forms.gle/abc"), kinds)
        self.assertNotIn(("email", "me@x.com"), kinds)         # job-seeker post ignored


if __name__ == "__main__":
    unittest.main()
