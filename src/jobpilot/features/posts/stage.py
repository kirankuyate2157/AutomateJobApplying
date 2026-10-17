from __future__ import annotations

import argparse

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult
from .runner import run_posts


class PostsStage:
    name = "posts"
    description = "Scroll LinkedIn hiring posts, extract emails/phones/forms into the contacts table"

    def run(self, ctx: AppContext) -> StageResult:
        if not ctx.settings.posts.enabled:
            return StageResult(self.name, True, notes="disabled in settings (posts.enabled)")
        from ...browser.linkedin.posts import LinkedInPostSource
        from ...browser.linkedin.session import ensure_logged_in

        ensure_logged_in(ctx.driver)
        s = run_posts(ctx.repo, LinkedInPostSource(ctx), ctx.settings.posts)
        return StageResult(self.name, True, {"scanned": s.scanned, "hiring": s.hiring,
                                             "new_contacts": s.new_contacts, "duplicates": s.duplicates})


stages.register("posts")(PostsStage())


def _configure(p: argparse.ArgumentParser) -> None:
    p.add_argument("--keyword", action="append", help="override settings keywords (repeatable)")


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    if args.keyword:
        ctx.settings.posts.keywords = args.keyword
    print(PostsStage().run(ctx))
    return 0


commands.register("posts")(Command("posts", "Scan LinkedIn hiring posts for contacts", _run, _configure))
