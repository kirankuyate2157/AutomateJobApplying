"""System feature: init, doctor, run (the orchestrator that executes configured stages)."""
from __future__ import annotations

import argparse
import importlib.util
import logging
import shutil
from importlib import resources
from pathlib import Path

from ...core.command import Command
from ...core.context import AppContext
from ...core.registry import commands, stages
from ...core.stage import StageResult
from ...exceptions import ConfigError
from ...reporting.report import today_report
from ..outreach.templates import DEFAULT_HTML, DEFAULT_TEXT

log = logging.getLogger(__name__)


# ------------------------------------------------------------------- init ----
def _init(_ctx, args: argparse.Namespace) -> int:
    root = Path(args.config).resolve().parent.parent
    pairs = [("settings.example.yaml", root / "config" / "settings.yaml"),
             ("profile.example.yaml", root / "config" / "profile.yaml"),
             ("env.example", root / ".env")]
    for resource, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(f"keep    {target}")
            continue
        target.write_text((resources.files("jobpilot") / "resources" / resource).read_text(encoding="utf-8"),
                          encoding="utf-8")
        print(f"created {target}")
    tdir = root / "config" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    for name, body in (("application_email.txt", DEFAULT_TEXT), ("application_email.html", DEFAULT_HTML)):
        if not (tdir / name).exists():
            (tdir / name).write_text(body, encoding="utf-8")
            print(f"created {tdir / name}")
    for d in ("data/resumes", "data/exports", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    print("\nNext: edit config/profile.yaml, drop your resume PDFs in data/resumes/, then run `jobpilot doctor`.")
    return 0


# ----------------------------------------------------------------- doctor ----
def _doctor(_ctx, args: argparse.Namespace) -> int:
    from ...core.bootstrap import build_context
    problems = 0

    def check(ok: bool, msg: str, hint: str = "", blocking: bool = True) -> None:
        nonlocal problems
        print(f"  [{'ok' if ok else ('!!' if blocking else '..')}] {msg}" + ("" if ok or not hint else f"\n        -> {hint}"))
        problems += (not ok) and blocking

    print("JobPilot doctor")
    try:
        ctx = build_context(args)
    except (ConfigError, FileNotFoundError) as exc:
        check(False, f"configuration: {exc}", "run `jobpilot init`, then edit config/profile.yaml")
        return 1
    s, p = ctx.settings, ctx.profile
    check(True, f"settings + profile load ({p.full_name}, {p.total_years:g} yrs)")
    check(bool(p.resumes), "at least one resume variant configured", "add `resumes:` to profile.yaml")
    for r in p.resumes:
        check(s.path(r.path).exists(), f"resume file exists: {r.path}", "copy your PDF there")
    check(s.apply.dry_run, "dry_run is ON (recommended until a dry run looks right)", blocking=False)
    check(importlib.util.find_spec("selenium") is not None, "selenium installed",
          "pip install 'jobpilot[browser]'")
    check(shutil.which("google-chrome") is not None or shutil.which("chrome") is not None or shutil.which("chromium") is not None
          or True, "Chrome (assumed installed; Selenium Manager fetches the driver)", blocking=False)
    if s.llm.provider != "none":
        from ...settings import env
        check(bool(env(s.llm.api_key_env)), f"LLM key present in env {s.llm.api_key_env}",
              "put it in .env (it is git-ignored)")
    if s.mail.enabled:
        from ...settings import env
        check(bool(env(s.mail.user_env) and env(s.mail.password_env)), "SMTP credentials present in .env",
              "use a Gmail App Password, never your real password")
    pending = ctx.repo.count("questions", "status=?", ("pending",))
    check(pending == 0, f"{pending} question(s) waiting for your answer", "jobpilot answers list", blocking=False)
    ctx.close()
    print("\nAll blocking checks passed." if not problems else f"\n{problems} blocking problem(s).")
    return 1 if problems else 0


# -------------------------------------------------------------------- run ----
def _run_cfg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--only", action="append", help="run only these stages (repeatable)")
    p.add_argument("--skip-export", action="store_true", help="do not auto-export CSV/Excel afterwards")


def _run(ctx: AppContext, args: argparse.Namespace) -> int:
    """Execute the configured stages in order. A failing stage never stops the others."""
    names = args.only or ctx.settings.pipeline.stages
    mode = "DRY RUN (nothing is submitted)" if ctx.dry_run else "LIVE"
    print(f"JobPilot run: {mode}; stages: {', '.join(names)}")
    results: list[StageResult] = []
    for name in names:
        try:
            stage = stages.get(name)
        except KeyError as exc:
            results.append(StageResult(name, False, notes=str(exc)))
            continue
        try:
            results.append(stage.run(ctx))
        except Exception as exc:               # isolate failures: posts failing must not skip mail/export
            log.exception("stage %s crashed", name)
            results.append(StageResult(name, False, notes=f"{type(exc).__name__}: {exc}"))
        print(results[-1])
    if not args.skip_export:
        from ..reports import export_all
        try:
            paths = export_all(ctx, ["xlsx"])
            print("exported:", ", ".join(str(x) for x in paths))
        except Exception:
            log.exception("export failed")
    print("\n" + today_report(ctx.repo, ctx.settings.apply.daily_target))
    return 0 if all(r.ok for r in results) else 1


commands.register("init")(Command("init", "Create config files from templates", _init, needs_context=False))
commands.register("doctor")(Command("doctor", "Check configuration and environment", _doctor, needs_context=False))
commands.register("run")(Command("run", "Run all configured stages (posts, jobs, outreach)", _run, _run_cfg))
