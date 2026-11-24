"""Job application commands with multiple modes:

    jobpilot apply auto         Auto search + apply (score-based filtering)
    jobpilot apply manual       Manual control: you click Easy Apply, bot fills forms
    jobpilot apply browse       Manual browse only: skip searching, just wait for you to click Easy Apply
    jobpilot apply dry-run      Dry run: fill forms but don't submit (test mode)

Options:
    --min-score N       Minimum score to apply (0-100, default from settings)
    --limit N           Max jobs to apply in this run
    --no-filter         Apply to all jobs regardless of score
    --live              Really submit (overrides dry_run)
    --dry-run           Force dry run (overrides settings)
"""
from __future__ import annotations

import argparse
import sys

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult


def _configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="mode", help="Apply mode")

    # ---- auto ------------------------------------------------------------
    auto = sub.add_parser("auto", help="Auto search + apply with score filtering")
    auto.add_argument("--min-score", type=int, default=None, help="Minimum score (0-100)")
    auto.add_argument("--limit", type=int, default=None, help="Max jobs this run")
    auto.add_argument("--no-filter", action="store_true", help="Apply to all jobs regardless of score")
    _add_common(auto)

    # ---- manual ----------------------------------------------------------
    man = sub.add_parser("manual", help="Manual control: you click Easy Apply, bot fills forms")
    man.add_argument("--limit", type=int, default=None, help="Max jobs this run")
    _add_common(man)

    # ---- browse ----------------------------------------------------------
    browse = sub.add_parser("browse", help="Manual browse only: skip searching, wait for you to click Easy Apply")
    browse.add_argument("--limit", type=int, default=None, help="Max jobs this run")
    _add_common(browse)

    # ---- dry-run ---------------------------------------------------------
    dry = sub.add_parser("dry-run", help="Dry run: fill forms but don't submit")
    dry.add_argument("--min-score", type=int, default=None, help="Minimum score (0-100)")
    dry.add_argument("--limit", type=int, default=None, help="Max jobs this run")
    dry.add_argument("--no-filter", action="store_true", help="Apply to all jobs regardless of score")
    _add_common(dry)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--live", action="store_true", help="Really submit (overrides dry_run)")
    p.add_argument("--dry-run", action="store_true", help="Force dry run (overrides settings)")


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    # Heavy imports happen here
    from ...browser.linkedin.easy_apply import EasyApplier
    from ...browser.linkedin.jobs import LinkedInJobSource
    from ...browser.linkedin.session import ensure_logged_in
    from ...search.strategy import QueryPlanner
    from ...features.jobs.runner import DailyRunner

    cfg = ctx.settings.apply

    # Apply CLI overrides
    if args.live:
        cfg.dry_run = False
    if args.dry_run:
        cfg.dry_run = True
    if args.min_score is not None:
        cfg.min_score = args.min_score
    if args.limit:
        cfg.daily_target = args.limit + ctx.repo.count_applied_today()
    if args.no_filter:
        cfg.min_score = 0

    # Set mode
    if args.mode == "browse":
        cfg.manual_browse_only = True
        cfg.manual_control = False
    elif args.mode == "manual":
        cfg.manual_control = True
        cfg.manual_browse_only = False
    else:
        cfg.manual_control = False
        cfg.manual_browse_only = False

    mode_desc = {
        "auto": "AUTO: search + apply with score filtering",
        "manual": "MANUAL: you click Easy Apply, bot fills forms",
        "browse": "BROWSE: skip searching, wait for you to click Easy Apply",
        "dry-run": "DRY RUN: fill forms but don't submit",
    }.get(args.mode, "auto")

    mode_line = f"\n{'=' * 60}\n  MODE: {mode_desc}\n{'=' * 60}\n"
    print(mode_line)

    ensure_logged_in(ctx.driver)
    planner = QueryPlanner(ctx.profile, ctx.settings.search, ctx.repo)
    runner = DailyRunner(ctx.repo, ctx.profile, ctx.settings, planner,
                         LinkedInJobSource(ctx), EasyApplier(ctx), dry_run=ctx.dry_run)
    s = runner.run()
    print(result_summary(s))
    return 0 if s.stopped == "" or "daily target" in s.stopped else 1


def result_summary(s) -> str:
    lines = [
        "\n" + "=" * 60,
        "  RESULTS",
        "=" * 60,
        f"  Applied : {s.applied}",
        f"  Dry Run : {s.dry_run_ok}",
        f"  Skipped : {s.skipped}",
        f"  Needs Review : {s.needs_review}",
        f"  External : {s.external}",
        f"  Failed : {s.failed}",
        f"  Total Seen : {s.seen}",
        "=" * 60 + "\n",
    ]
    return "\n".join(lines)


# -----------------------------------------------------------------------
# JobsStage - original apply stage (used by `jobpilot --live run --only jobs`)
# -----------------------------------------------------------------------
class JobsStage:
    name = "jobs"
    description = "Search fresh LinkedIn jobs, score them and Easy Apply up to the daily target"

    def run(self, ctx: AppContext) -> StageResult:
        from ...browser.linkedin.easy_apply import EasyApplier
        from ...browser.linkedin.jobs import LinkedInJobSource
        from ...browser.linkedin.session import ensure_logged_in
        from ...features.jobs.runner import DailyRunner
        from ...search.strategy import QueryPlanner

        ensure_logged_in(ctx.driver)
        planner = QueryPlanner(ctx.profile, ctx.settings.search, ctx.repo)
        runner = DailyRunner(ctx.repo, ctx.profile, ctx.settings, planner,
                             LinkedInJobSource(ctx), EasyApplier(ctx), dry_run=ctx.dry_run)
        s = runner.run()
        return StageResult(self.name, True, {
            "seen": s.seen, "applied": s.applied, "dry_run_ok": s.dry_run_ok, "skipped": s.skipped,
            "needs_review": s.needs_review, "external": s.external, "failed": s.failed}, s.stopped)


stages.register("jobs")(JobsStage())

commands.register("apply")(Command("apply", "Apply to jobs with multiple modes", _run, _configure))