"""LinkedIn network outreach stage: connection requests, DMs, follow-ups,
referrals.

New feature branch: feature/linkedin-network-outreach.
Never modifies existing outreach email code (drafts.py, mailer.py, templates.py,
stage.py). Adds LinkedIn-native outreach on top.

CLI commands:
  jobpilot network connect   -- send connection requests
  jobpilot network dm        -- send direct messages
  jobpilot network followup  -- send due follow-ups
  jobpilot network referral  -- send referral requests
  jobpilot network stats     -- show outreach statistics
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult
from .network import NetworkAutomation

log = logging.getLogger(__name__)


class NetworkOutreachStage:
    name = "network"
    description = (
        "LinkedIn network outreach: connection requests, DMs, follow-ups, "
        "referrals with experiment tracking, dedup, and spacing delays"
    )

    def run(self, ctx: AppContext) -> StageResult:
        cfg = ctx.settings.outreach
        if not cfg.enabled:
            return StageResult(self.name, True, notes="disabled (outreach.enabled)")
        auto = NetworkAutomation(ctx)
        result = auto.run()
        result_dict: dict[str, Any] = {
            "contacted": result.contacted,
            "skipped": result.skipped,
            "failed": result.failed,
            "daily_cap_reached": result.daily_cap_reached,
            "stats": auto.stats(),
        }
        return StageResult(self.name, True, result_dict)


stages.register("network")(NetworkOutreachStage())


# ---------------------------------------------------------------- CLI commands --

def _configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", required=True)

    connect = sub.add_parser("connect", help="send connection requests")
    connect.add_argument("--limit", type=int, default=None)

    dm = sub.add_parser("dm", help="send direct messages")
    dm.add_argument("--limit", type=int, default=None)

    followup = sub.add_parser("followup", help="send due follow-ups")
    followup.add_argument("--limit", type=int, default=None)

    referral = sub.add_parser("referral", help="send referral requests")
    referral.add_argument("--limit", type=int, default=None)

    sub.add_parser("stats", help="show outreach statistics")


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    auto = NetworkAutomation(ctx)

    if args.action == "stats":
        s = auto.stats()
        print("=== Outreach Statistics ===")
        for kind, statuses in s.items():
            print(f"  {kind}:")
            for status, count in statuses.items():
                print(f"    {status}: {count}")
        return 0

    result = auto.run(limit=args.limit)
    print(f"contacted={result.contacted} skipped={result.skipped} "
          f"failed={result.failed} daily_cap_reached={result.daily_cap_reached}")
    return 0


commands.register("network")(
    Command("network", "LinkedIn network outreach (connect, dm, followup, referral)", _run, _configure)
)
