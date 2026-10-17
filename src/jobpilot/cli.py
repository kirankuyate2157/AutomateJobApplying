"""Command-line entry point. Commands come from the registry, not from this file.

Adding a command never touches cli.py: a module registers a `Command` in
core.registry.commands and (if it lives in features/ or a configured plugin)
is auto-loaded by core.plugins.
"""
from __future__ import annotations

import argparse
import sys

from .core.bootstrap import build_context
from .core.plugins import load_plugins
from .core.registry import commands
from .exceptions import ConfigError, JobPilotError
from .settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobpilot", description="Targeted LinkedIn applications + hiring-post outreach")
    parser.add_argument("--config", default="config/settings.yaml", help="path to settings.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="really submit applications / send mail (overrides dry_run)")
    mode.add_argument("--dry-run", action="store_true", help="force dry run even if settings say live")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, cmd in commands.items():
        cmd.configure(sub.add_parser(name, help=cmd.help, description=cmd.help))
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # pre-parse --config so settings.yaml can add plugins BEFORE the parser is built
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="config/settings.yaml")
    known, _ = pre.parse_known_args(argv)
    try:
        settings = Settings.load(known.config)
    except ConfigError:
        settings = None                      # `init` / `doctor` must work without a config
    load_plugins(settings)

    args = build_parser().parse_args(argv)
    cmd = commands.get(args.command)
    ctx = None
    try:
        if cmd.needs_context:
            ctx = build_context(args)
        return cmd.run(ctx, args)
    except JobPilotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        if ctx is not None:
            ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
