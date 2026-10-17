"""Module discovery.

Three ways a module gets loaded (all end in importing a python module whose
top level registers into core.registry):

  1. BUILT-IN   the list below (jobs, posts, outreach, reporting, ui)
  2. CONFIG     `plugins: [my_pkg.my_module]` in settings.yaml  (drop a file in
                your project, no packaging needed)
  3. ENTRY POINT   other pip packages that declare the `jobpilot.plugins`
                entry-point group

WHY: you can add `naukri`, `indeed` or `wellfound` support as a separate file
without touching core code, and a broken plugin cannot stop built-ins loading.
"""
from __future__ import annotations

import importlib
import logging
from importlib import metadata

from ..settings import Settings

log = logging.getLogger(__name__)

BUILTIN_MODULES = (
    "jobpilot.features.jobs",
    "jobpilot.features.posts",
    "jobpilot.features.outreach",
    "jobpilot.features.answers",
    "jobpilot.features.reports",
)


def load_plugins(settings: Settings | None = None) -> list[str]:
    """Import all modules; returns the names that failed (already logged)."""
    failed: list[str] = []
    names = list(BUILTIN_MODULES) + (list(settings.plugins) if settings else [])
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:       # a broken plugin must not take the app down
            failed.append(name)
            log.error("failed to load module %s: %s", name, exc, exc_info=log.isEnabledFor(logging.DEBUG))
    try:
        for ep in metadata.entry_points(group="jobpilot.plugins"):
            try:
                ep.load()
            except Exception as exc:
                failed.append(ep.name)
                log.error("failed to load entry point %s: %s", ep.name, exc)
    except Exception:                  # very old/odd metadata backends
        log.debug("entry point discovery failed", exc_info=True)
    return failed
