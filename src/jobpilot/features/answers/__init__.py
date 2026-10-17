"""Answers feature: review/teach the question bank (CLI). Same data the web UI edits."""
from __future__ import annotations

import argparse
import json

from ...answering.normalize import normalize_question
from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands
from ...storage.legacy_import import import_legacy_csv


def _configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="list questions (default: those needing an answer)")
    ls.add_argument("--status", default="pending", choices=["pending", "legacy", "user", "cached", "auto", "all"])
    st = sub.add_parser("set", help="teach an answer once; it is reused for every future application")
    st.add_argument("question")
    st.add_argument("answer")
    sub.add_parser("promote-legacy", help="approve ALL imported legacy answers (review them first!)")
    imp = sub.add_parser("import-legacy", help="import the old bot's applied-jobs CSV")
    imp.add_argument("csv_path")


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    repo = ctx.repo
    if args.action == "list":
        rows = repo.list_questions(None if args.status == "all" else args.status)
        for q in rows:
            opts = json.loads(q["options_json"] or "[]")
            print(f'[{q["status"]:<7}] x{q["times_seen"]:<3} {q["text"][:90]}')
            if opts:
                print(f"           options: {opts[:8]}")
            if q["answer"]:
                print(f"           answer : {q['answer'][:90]}  ({q['source']})")
        print(f"\n{len(rows)} question(s). Teach one with:  jobpilot answers set \"<question>\" \"<answer>\"")
    elif args.action == "set":
        key = normalize_question(args.question)
        if not repo.set_user_answer(key, args.answer):
            repo.record_question(key, args.question, "text", [], args.answer, "user", 1.0, "user")
        print(f"saved: {key!r} -> {args.answer!r}")
    elif args.action == "promote-legacy":
        print(f"promoted {repo.promote_legacy()} legacy answers")
    elif args.action == "import-legacy":
        print(import_legacy_csv(repo, args.csv_path))
    return 0


commands.register("answers")(Command("answers", "Review and teach question answers", _run, _configure))
