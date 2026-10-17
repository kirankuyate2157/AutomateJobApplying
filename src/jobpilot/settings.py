"""Typed, validated settings loaded from config/settings.yaml (+ .env secrets).

WHY dataclasses instead of the legacy `from config.x import *` modules:
  * one explicit object is passed around (no hidden globals / import side effects)
  * unknown keys raise an error, so a typo like `daily_targt` is caught at start
  * defaults live in code, the YAML only overrides what you care about

SUGGESTION: if settings grow large, swap the hand-rolled loader for pydantic;
the dataclass layout maps 1:1.
"""
from __future__ import annotations

import dataclasses
import os
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigError


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
@dataclass
class ApplySettings:
    daily_target: int = 30            # the "30 targeted applications / day" goal
    dry_run: bool = True              # SAFE DEFAULT: fill forms but never press Submit
    min_score: int = 50               # jobs scoring below this are skipped (0-100)
    max_per_hour: int = 12            # sliding-window cap; looks human, avoids flags
    delay_min_s: float = 3.0          # random pause between applications
    delay_max_s: float = 9.0
    max_pages_per_query: int = 4      # result pages scanned per search
    unfollow_company: bool = True     # untick "follow company" on submit
    overwrite_prefilled: bool = False # keep values LinkedIn pre-filled (phone/email)


@dataclass
class SearchSettings:
    extra_keywords: list[str] = field(default_factory=list)  # added to profile.target_roles
    locations: list[str] = field(default_factory=lambda: ["India"])
    freshness_seconds: int = 86400            # first pass: only jobs posted <24h ago
    fallback_freshness_seconds: int = 604800  # second pass if quota not met: 7 days
    easy_apply_only: bool = True
    experience_levels: list[int] = field(default_factory=lambda: [2, 3, 4])  # LinkedIn f_E codes
    work_types: list[int] = field(default_factory=list)  # f_WT: 1 on-site 2 remote 3 hybrid; [] = any
    sort_by: str = "DD"                       # DD = most recent, R = most relevant


@dataclass
class LLMSettings:
    provider: str = "none"            # none | gemini | openai   (openai = any OpenAI-compatible API)
    model: str = "gemini-flash-latest"
    base_url: str = "https://api.openai.com/v1"   # Groq/OpenRouter/Ollama also work here
    api_key_env: str = "GEMINI_API_KEY"
    min_confidence: float = 0.7
    timeout_s: int = 30
    max_retries: int = 2


@dataclass
class AnswerSettings:
    min_confidence: float = 0.7       # rule answers below this are treated as "unsure"
    cache_llm_answers: bool = True    # reuse LLM answers for identical (non-textarea) questions


@dataclass
class MailSettings:
    enabled: bool = False
    auto_send: bool = False           # False = drafts wait for `jobpilot mail approve`
    daily_cap: int = 40
    max_per_domain_per_day: int = 2
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    user_env: str = "SMTP_USER"
    password_env: str = "SMTP_APP_PASSWORD"
    delay_min_s: float = 25.0
    delay_max_s: float = 70.0
    attach_resume: bool = True
    template: str = "application_email"


@dataclass
class PostSettings:
    enabled: bool = True
    keywords: list[str] = field(default_factory=lambda: [
        "hiring python developer", "hiring full stack developer",
        "hiring backend engineer", "hiring node js developer",
        "hiring software engineer", "send your resume python"])
    date_filter: str = "past-24h"     # LinkedIn content-search filter: past-24h | past-week
    max_scrolls: int = 12
    max_posts_per_keyword: int = 60
    min_hiring_score: int = 3


@dataclass
class BrowserSettings:
    headless: bool = False
    user_data_dir: str = "data/chrome-profile"   # persistent login, separate from your daily Chrome
    page_load_timeout_s: int = 40
    window_size: str = "1366,900"


@dataclass
class PathsSettings:
    data_dir: str = "data"
    log_dir: str = "logs"
    templates_dir: str = "config/templates"


@dataclass
class Settings:
    apply: ApplySettings = field(default_factory=ApplySettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    answers: AnswerSettings = field(default_factory=AnswerSettings)
    mail: MailSettings = field(default_factory=MailSettings)
    posts: PostSettings = field(default_factory=PostSettings)
    browser: BrowserSettings = field(default_factory=BrowserSettings)
    paths: PathsSettings = field(default_factory=PathsSettings)
    root: Path = field(default_factory=Path.cwd)   # project root; not settable from YAML

    # -- helpers ----------------------------------------------------------- #
    def path(self, relative: str) -> Path:
        """Resolve a config-relative path against the project root."""
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

    @property
    def db_path(self) -> Path:
        return self.path(self.paths.data_dir) / "jobpilot.db"

    @classmethod
    def load(cls, path: str | Path = "config/settings.yaml") -> "Settings":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"{path} not found. Run `jobpilot init` to create it.")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
        raw.pop("root", None)
        settings = _build(cls, raw, where="settings")
        settings.root = path.resolve().parent.parent   # config/ lives directly under root
        return settings


# --------------------------------------------------------------------------- #
# Generic dict -> dataclass builder (strict about unknown keys)
# --------------------------------------------------------------------------- #
def _build(cls: type, data: dict[str, Any] | None, where: str) -> Any:
    data = data or {}
    if not isinstance(data, dict):
        raise ConfigError(f"'{where}' must be a mapping, got {type(data).__name__}")
    hints = typing.get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ConfigError(f"Unknown key(s) in '{where}': {sorted(unknown)}. Valid: {sorted(names)}")
    kwargs = {}
    for name, value in data.items():
        t = hints[name]
        kwargs[name] = _build(t, value, f"{where}.{name}") if dataclasses.is_dataclass(t) else value
    return cls(**kwargs)


# --------------------------------------------------------------------------- #
# .env loader (tiny on purpose: avoids a python-dotenv dependency)
# --------------------------------------------------------------------------- #
def load_env_file(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str, default: str = "") -> str:
    """Read a secret from the environment (single choke point for secrets)."""
    return os.environ.get(name, default)
