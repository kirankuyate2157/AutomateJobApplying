from __future__ import annotations

import argparse

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult
from ...search.strategy import QueryPlanner
from .runner import DailyRunner


class JobsStage:
    name = "jobs"
    description = "Search fresh LinkedIn jobs, score them and Easy Apply up to the daily target"

    def run(self, ctx: AppContext) -> StageResult:
        # heavy imports happen here, not at module import: keeps `--help` and tests Selenium-free
        from ...browser.linkedin.easy_apply import EasyApplier
        from ...browser.linkedin.jobs import LinkedInJobSource
        from ...browser.linkedin.session import ensure_logged_in

        ensure_logged_in(ctx.driver)
        planner = QueryPlanner(ctx.profile, ctx.settings.search, ctx.repo)
        runner = DailyRunner(ctx.repo, ctx.profile, ctx.settings, planner,
                             LinkedInJobSource(ctx), EasyApplier(ctx), dry_run=ctx.dry_run)
        s = runner.run()
        return StageResult(self.name, True, {
            "seen": s.seen, "applied": s.applied, "dry_run_ok": s.dry_run_ok, "skipped": s.skipped,
            "needs_review": s.needs_review, "external": s.external, "failed": s.failed}, s.stopped)


stages.register("jobs")(JobsStage())


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    if args.limit:
        ctx.settings.apply.daily_target = args.limit + ctx.repo.count_applied_today()
    result = JobsStage().run(ctx)
    print(result)
    return 0 if result.ok else 1


def _configure(p: argparse.ArgumentParser) -> None:
    p.add_argument("--limit", type=int, help="apply to at most N jobs in this run (on top of today's count)")


commands.register("apply")(Command("apply", "Run only the job-application stage", _run, _configure))
