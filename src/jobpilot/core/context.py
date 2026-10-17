"""AppContext: everything a stage/command needs, built lazily.

WHY lazily: `jobpilot answers list` must not start Chrome or need an API key;
`jobpilot apply` should only build the LLM client if it is configured. Each
heavy dependency is created on first access and closed once at the end.

This replaces the legacy pattern of importing modules that opened Chrome as a
side effect of `import`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..answering.engine import AnswerEngine
from ..answering.llm import LLMClient, make_llm
from ..profile.profile import Profile
from ..settings import Settings
from ..storage.db import Repository

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    profile: Profile
    repo: Repository
    dry_run: bool = True                       # mirrors settings.apply.dry_run unless overridden
    _llm: Any = field(default=None, repr=False)
    _llm_built: bool = field(default=False, repr=False)
    _engine: AnswerEngine | None = field(default=None, repr=False)
    _driver: Any = field(default=None, repr=False)

    @property
    def llm(self) -> LLMClient | None:
        if not self._llm_built:
            self._llm, self._llm_built = make_llm(self.settings.llm), True
        return self._llm

    @property
    def engine(self) -> AnswerEngine:
        if self._engine is None:
            self._engine = AnswerEngine(self.repo, self.profile, self.settings.answers, self.llm,
                                        self.settings.llm.min_confidence)
        return self._engine

    @property
    def driver(self):
        """Selenium driver, started on first use and shared by all browser stages
        (one LinkedIn session; see docs/ARCHITECTURE.md on why not parallel)."""
        if self._driver is None:
            from ..browser.driver import make_driver     # lazy: selenium is an optional extra
            self._driver = make_driver(self.settings)
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:                            # browser may already be gone
                log.debug("driver.quit() failed", exc_info=True)
            self._driver = None
        self.repo.close()
