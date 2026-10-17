"""Daily job-application orchestration (pure logic, no browser imports).

Flow per search spec (best-yield first):
    for each job found -> dedupe -> harvest contacts -> score -> filter
        -> pick resume -> throttle -> apply -> record -> pace
until today's quota (daily_target minus already applied today) is filled.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Callable

from ...extraction.harvest import harvest_text
from ...profile.profile import Profile
from ...resumes.selector import choose_resume
from ...scoring.job_scorer import JobScorer
from ...search.strategy import QueryPlanner, SearchSpec
from ...settings import Settings
from ...storage.db import Repository
from ...domain.models import Job
from ...exceptions import DailyLimitReached, ManualInterventionRequired
from .ports import Applier, JobSource
from .throttle import HourlyThrottle

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    seen: int = 0
    applied: int = 0          # live submissions
    dry_run_ok: int = 0       # would have been submitted
    skipped: int = 0
    external: int = 0
    needs_review: int = 0
    failed: int = 0
    stopped: str = ""         # why the run ended early, if it did

    @property
    def done(self) -> int:
        return self.applied + self.dry_run_ok


class DailyRunner:
    def __init__(self, repo: Repository, profile: Profile, settings: Settings, planner: QueryPlanner,
                 source: JobSource, applier: Applier, dry_run: bool,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
        self.repo, self.profile, self.settings = repo, profile, settings
        self.planner, self.source, self.applier, self.dry_run = planner, source, applier, dry_run
        self.scorer = JobScorer(profile)
        self.throttle = HourlyThrottle(settings.apply.max_per_hour, sleep=sleep)
        self.sleep, self.rng = sleep, rng or random.Random()

    def run(self) -> RunSummary:
        cfg = self.settings.apply
        summary = RunSummary()
        remaining = cfg.daily_target - self.repo.count_applied_today()
        if remaining <= 0:
            summary.stopped = f"daily target {cfg.daily_target} already met"
            return summary
        run_id = self.repo.start_run(self.dry_run)
        try:
            for spec in self.planner.plan():
                if summary.done >= remaining:
                    break
                self._run_spec(spec, summary, remaining)
        except DailyLimitReached as exc:
            summary.stopped = str(exc)
        except ManualInterventionRequired as exc:
            summary.stopped = f"needs human: {exc}"
        finally:
            self.repo.finish_run(run_id, summary.done, summary.skipped, summary.failed,
                                 summary.needs_review, summary.stopped)
        return summary

    # ------------------------------------------------------------- internals
    def _run_spec(self, spec: SearchSpec, summary: RunSummary, remaining: int) -> None:
        seen = done = 0
        log.info("searching %r (pass %d)", spec.key, spec.pass_no)
        try:
            for job in self.source.iter_jobs(spec):
                seen += 1
                summary.seen += 1
                status = self._handle(job, spec, summary)
                if status in ("applied", "dry_run_ok"):
                    done += 1
                if summary.done >= remaining:
                    log.info("daily quota filled")
                    break
        finally:
            self.repo.record_search(spec.key, seen, done)   # feeds the yield-learning planner

    def _handle(self, job: Job, spec: SearchSpec, summary: RunSummary) -> str:
        repo, cfg = self.repo, self.settings.apply
        if repo.job_is_final(job.job_id, self.dry_run):
            return "known"
        repo.upsert_job(job, spec.key)
        # contacts in ANY description are valuable even if we skip the job
        harvest_text(repo, job.description, "job", job.job_id)

        score = self.scorer.score(job)
        repo.upsert_job(job, spec.key, score=score.total)
        if score.reject_reason or score.total < cfg.min_score:
            reason = score.reject_reason or f"score {score.total:.0f} < {cfg.min_score}"
            repo.set_job_status(job.job_id, "skipped", reason)
            summary.skipped += 1
            log.info("skip  %-40.40s | %s", f"{job.title} @ {job.company}", reason)
            return "skipped"

        resume = choose_resume(self.profile, set(score.required_skills), self.settings.root)
        resume_path = str(self.settings.path(resume.path)) if resume else ""
        self.throttle.wait()
        result = self.applier.apply(job, resume_path)
        repo.set_job_status(job.job_id, result.status, result.reason, result.resume or (resume.label if resume else ""),
                            result.external_url)
        log.info("%-12s %-40.40s | score %.0f | %s", result.status, f"{job.title} @ {job.company}", score.total, result.reason)

        if result.status == "applied":
            summary.applied += 1
            self.throttle.mark()
        elif result.status == "dry_run_ok":
            summary.dry_run_ok += 1
        elif result.status == "needs_review":
            summary.needs_review += 1
        elif result.status == "external":
            summary.external += 1
        else:
            summary.failed += 1
        if result.status in ("applied", "dry_run_ok", "failed"):
            self.sleep(self.rng.uniform(cfg.delay_min_s, cfg.delay_max_s))      # human-like pacing
        return result.status
