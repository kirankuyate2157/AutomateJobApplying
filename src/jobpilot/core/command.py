"""CLI command contract: modules register a Command, cli.py builds the parser from them."""
from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import Callable

from .context import AppContext


@dataclass
class Command:
    name: str
    help: str
    run: Callable[[AppContext, Namespace], int]
    configure: Callable[[ArgumentParser], None] = lambda parser: None
    needs_context: bool = True      # False for commands that must work before config exists
