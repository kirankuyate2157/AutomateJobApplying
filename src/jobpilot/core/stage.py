"""The Stage contract every pipeline module implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .context import AppContext


@dataclass
class StageResult:
    stage: str
    ok: bool = True
    counts: dict[str, int] = field(default_factory=dict)   # e.g. {"applied": 12, "skipped": 40}
    notes: str = ""

    def __str__(self) -> str:
        c = ", ".join(f"{k}={v}" for k, v in self.counts.items())
        return f"[{self.stage}] {'ok' if self.ok else 'FAILED'} {c} {self.notes}".strip()


@runtime_checkable
class Stage(Protocol):
    """A unit of work. Must be re-runnable (idempotent): the database dedupes."""
    name: str
    description: str

    def run(self, ctx: AppContext) -> StageResult: ...
