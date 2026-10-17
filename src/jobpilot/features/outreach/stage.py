from __future__ import annotations

import argparse

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult
from .drafts import draft_from_contacts
from .mailer import Mailer


class OutreachStage:
    name = "outreach"
    description = "Draft application mails for harvested emails; send approved ones (rate-limited)"

    def run(self, ctx: AppContext) -> StageResult:
        cfg = ctx.settings.mail
        if not cfg.enabled:
            return StageResult(self.name, True, notes="disabled in settings (mail.enabled)")
        drafted = draft_from_contacts(ctx.repo, ctx.profile, ctx.settings)
        counts = {"drafted": drafted}
        if cfg.auto_send and not ctx.dry_run:
            counts.update(Mailer(cfg, ctx.repo, ctx.profile).send_approved())
        elif cfg.auto_send:
            return StageResult(self.name, True, counts, "dry-run: drafts created, nothing sent")
        return StageResult(self.name, True, counts)


stages.register("outreach")(OutreachStage())


# ---------------------------------------------------------------- `mail` CLI --
def _configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("draft", help="create drafts from harvested contacts")
    sub.add_parser("list", help="show the mail queue")
    sub.add_parser("approve", help="approve all pending drafts")
    send = sub.add_parser("send", help="send approved mails now")
    send.add_argument("--limit", type=int)


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    if args.action == "draft":
        print(f"created {draft_from_contacts(ctx.repo, ctx.profile, ctx.settings)} drafts")
    elif args.action == "list":
        for r in ctx.repo.mail_batch(["pending", "approved", "sent", "failed", "skipped"], 500):
            print(f'{r["id"]:>4} {r["status"]:<9} {r["to_email"]:<35} {r["subject"][:60]}')
    elif args.action == "approve":
        print(f"approved {ctx.repo.approve_pending_mail()} drafts")
    elif args.action == "send":
        print(Mailer(ctx.settings.mail, ctx.repo, ctx.profile).send_approved(args.limit))
    return 0


commands.register("mail")(Command("mail", "Manage outreach mail drafts and sending", _run, _configure))
