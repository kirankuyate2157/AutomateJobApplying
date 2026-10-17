"""Build an AppContext from CLI arguments (config + .env + profile + database)."""
from __future__ import annotations

import argparse
from pathlib import Path

from ..logging_setup import setup_logging
from ..profile.profile import Profile
from ..settings import Settings, load_env_file
from ..storage.db import Repository
from .context import AppContext


def build_context(args: argparse.Namespace) -> AppContext:
    settings = Settings.load(args.config)
    load_env_file(settings.root / ".env")              # secrets, after root is known
    setup_logging(settings.path(settings.paths.log_dir), getattr(args, "verbose", False))
    profile = Profile.load(settings.root / "config" / "profile.yaml")
    dry_run = settings.apply.dry_run
    if getattr(args, "live", False):
        dry_run = False
    if getattr(args, "dry_run", False):
        dry_run = True
    settings.apply.dry_run = dry_run
    return AppContext(settings, profile, Repository(settings.db_path), dry_run=dry_run)
