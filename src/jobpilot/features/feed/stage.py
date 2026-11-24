from __future__ import annotations

import argparse
import logging

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands
from ...core.registry import stages
from ...core.stage import StageResult
from .runner import run_feed

log = logging.getLogger(__name__)


class FeedStage:
    name = "feed"
    description = (
        "Scroll LinkedIn main feed, extract emails/phones/forms from hiring posts into the contacts table"
    )

    def run(self, ctx: AppContext) -> StageResult:
        if not ctx.settings.feed.enabled:
            return StageResult(self.name, True, notes="disabled in settings (feed.enabled)")
        from ...browser.linkedin.feed import LinkedInFeedSource
        from ...browser.linkedin.session import ensure_logged_in

        ensure_logged_in(ctx.driver)
        # Optional AI pass: refines company/requirements/emails using your LLM
        # key. Falls back to regex-only (free, offline) when no key configured.
        ai_extractor = None
        if ctx.settings.feed.ai_extract:
            if ctx.llm is not None:
                from ...extraction.contacts import AIPostExtractor

                ai_extractor = AIPostExtractor(ctx.llm, ctx.profile.llm_context())
            else:
                log.info(
                    "feed.ai_extract is on but no LLM key configured: using regex-only extraction"
                )

        s = run_feed(
            ctx.repo, LinkedInFeedSource(ctx), ctx.settings.feed, ai_extractor=ai_extractor
        )
        return StageResult(
            self.name,
            True,
            {
                "scanned": s.scanned,
                "hiring": s.hiring,
                "new_contacts": s.new_contacts,
                "duplicates": s.duplicates,
                "ai_extract": bool(ai_extractor),
            },
        )


stages.register("feed")(FeedStage())


def _configure(p: argparse.ArgumentParser) -> None:
    pass


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    print(FeedStage().run(ctx))
    return 0


commands.register("feed")(
    Command("feed", "Scan LinkedIn feed for hiring post contacts", _run, _configure)
)
