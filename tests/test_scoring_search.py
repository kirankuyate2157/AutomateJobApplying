import random
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from jobpilot.domain.models import Job
from jobpilot.profile.profile import Profile
from jobpilot.resumes.selector import choose_resume
from jobpilot.scoring.job_scorer import JobScorer
from jobpilot.search.strategy import QueryPlanner, SearchSpec, build_search_url
from jobpilot.settings import SearchSettings
from jobpilot.storage.db import Repository

NOW = datetime(2026, 10, 17, 12, 0)


def profile(**kw):
    base = dict(first_name="A", last_name="B", email="a@b.c", phone="9000000000", total_years=3,
                skills={"python": 3, "node.js": 3, "docker": 2, "aws": 1},
                target_roles=["Backend Developer", "Python Developer"], avoid_keywords=["php"],
                max_required_years=4, authorized_countries=["India"])
    base.update(kw)
    return Profile.from_dict(base)


def job(**kw):
    base = dict(job_id="1", title="Python Backend Developer", company="Acme", location="Pune, India",
                description="3+ years experience. Python, Docker, AWS, Node.js.", posted_at=NOW - timedelta(hours=2))
    base.update(kw)
    return Job(**base)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.scorer = JobScorer(profile(), now=NOW)

    def test_good_job_scores_high(self):
        s = self.scorer.score(job())
        self.assertIsNone(s.reject_reason)
        self.assertGreater(s.total, 75)
        self.assertEqual(set(s.matched_skills), {"python", "docker", "aws", "node.js"})

    def test_rejections(self):
        cases = {
            "php": job(description="PHP and Laravel, 2 years experience"),
            "requires": job(description="Minimum 8 years of experience in Python"),
            "outside": job(location="Austin, Texas, United States"),
            "clearance": job(description="Needs security clearance. 3 years experience"),
        }
        for name, j in cases.items():
            with self.subTest(name):
                self.assertIsNotNone(self.scorer.score(j).reject_reason)

    def test_remote_location_allowed(self):
        self.assertIsNone(self.scorer.score(job(location="Remote")).reject_reason)

    def test_fresh_beats_stale(self):
        fresh = self.scorer.score(job()).total
        stale = self.scorer.score(job(posted_at=NOW - timedelta(days=5))).total
        self.assertGreater(fresh, stale)

    def test_irrelevant_title_scores_low(self):
        s = self.scorer.score(job(title="Sales Manager", description="Sell things. 3 years experience."))
        self.assertLess(s.total, 50)


class ResumeTests(unittest.TestCase):
    def test_picks_by_overlap_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.pdf").write_bytes(b"x")
            (Path(d) / "b.pdf").write_bytes(b"x")
            p = profile(resumes=[
                {"path": "a.pdf", "label": "backend", "focus_skills": ["python", "aws"], "default": True},
                {"path": "b.pdf", "label": "front", "focus_skills": ["react"]},
                {"path": "missing.pdf", "label": "ghost", "focus_skills": ["python", "aws", "docker"]}])
            self.assertEqual(choose_resume(p, {"python", "aws"}, Path(d)).label, "backend")
            self.assertEqual(choose_resume(p, {"react"}, Path(d)).label, "front")


class SearchTests(unittest.TestCase):
    def test_url(self):
        url = build_search_url(SearchSpec("python developer", "India", 86400), SearchSettings(), page=2)
        for part in ("keywords=python+developer", "f_TPR=r86400", "f_AL=true", "sortBy=DD",
                     "f_E=2%2C3%2C4", "start=50"):
            self.assertIn(part, url)

    def test_planner_prefers_productive_queries_and_has_two_passes(self):
        repo = Repository(":memory:")
        cfg = SearchSettings(locations=["India"])
        planner = QueryPlanner(profile(), cfg, repo, rng=random.Random(1))
        winner = SearchSpec("Python Developer", "India", cfg.freshness_seconds)
        repo.record_search(winner.key, 30, 20)
        for k in ("Backend Developer",):                # explored, but never productive
            repo.record_search(SearchSpec(k, "India", cfg.freshness_seconds).key, 30, 0)
        plan = planner.plan()
        self.assertEqual(plan[0].keywords, "Python Developer")
        self.assertEqual({s.pass_no for s in plan}, {1, 2})
        self.assertEqual([s.pass_no for s in plan], sorted(s.pass_no for s in plan))


if __name__ == "__main__":
    unittest.main()
