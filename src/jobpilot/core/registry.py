"""A tiny generic registry: the backbone of the module system.

WHY: instead of hard-wiring "linkedin jobs, then posts, then mail" in one big
function (the legacy runAiBot.py did this in a 600-line file), every feature
registers itself by NAME. Adding a feature = adding a module that registers a
stage and, optionally, a CLI command. Nothing else is edited.

Three registries exist (see bottom of file):
  stages    - units of work the daily run executes (jobs, posts, mail, ...)
  commands  - CLI sub-commands (`jobpilot <name>`)
  exporters - table exporters (csv, xlsx, ... add json/google-sheets later)
"""
from __future__ import annotations

from typing import Callable, Generic, Iterator, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str) -> Callable[[T], T]:
        """Decorator: `@stages.register("jobs")`. Duplicate names are an error
        so two modules can never silently shadow each other."""
        def deco(obj: T) -> T:
            if name in self._items and self._items[name] is not obj:
                raise ValueError(f"{self.kind} '{name}' is already registered")
            self._items[name] = obj
            return obj
        return deco

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"unknown {self.kind} '{name}'. Available: {', '.join(sorted(self._items)) or 'none'}") from None

    def names(self) -> list[str]:
        return sorted(self._items)

    def items(self) -> Iterator[tuple[str, T]]:
        return iter(sorted(self._items.items()))

    def __contains__(self, name: str) -> bool:
        return name in self._items


stages: Registry = Registry("stage")
commands: Registry = Registry("command")
exporters: Registry = Registry("exporter")
