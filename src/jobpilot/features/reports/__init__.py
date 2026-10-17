"""Reports feature: `report`, `export`, `ui` commands."""
from __future__ import annotations

import argparse

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, exporters
from ...reporting import exporters as _builtin_exporters  # noqa: F401  (registers csv/xlsx)
from ...reporting.datasets import build_datasets
from ...reporting.report import today_report


def export_all(ctx: AppContext, formats: list[str] | None = None) -> list:
    out = ctx.settings.path(ctx.settings.paths.data_dir) / "exports"
    datasets = build_datasets(ctx.repo)
    paths = []
    for fmt in formats or ["csv", "xlsx"]:
        paths += exporters.get(fmt)(datasets, out / fmt if fmt == "csv" else out)
    return paths


def _report(ctx: AppContext, args: argparse.Namespace) -> int:
    print(today_report(ctx.repo, ctx.settings.apply.daily_target))
    return 0


def _export_cfg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", action="append", choices=exporters.names(), help="csv, xlsx (repeatable)")


def _export(ctx: AppContext, args: argparse.Namespace) -> int:
    for path in export_all(ctx, args.format):
        print("wrote", path)
    return 0


def _ui(ctx: AppContext, args: argparse.Namespace) -> int:
    from ...ui.app import create_app           # needs the optional 'ui' extra
    print(f"JobPilot UI on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    create_app(ctx).run(host="127.0.0.1", port=args.port)
    return 0


commands.register("report")(Command("report", "Print today's status report", _report))
commands.register("export")(Command("export", "Export all data to CSV/Excel", _export, _export_cfg))
commands.register("ui")(Command("ui", "Start the local dashboard", _ui,
                                lambda p: p.add_argument("--port", type=int, default=5000)))
