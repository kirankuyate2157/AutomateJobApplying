"""Sliding-window rate limiter (max N applications per rolling hour).

WHY: 30 applications fired in 10 minutes looks robotic and is what gets
accounts flagged. Spreading them is safer and costs nothing.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class HourlyThrottle:
    def __init__(self, max_per_hour: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.max, self.clock, self.sleep = max_per_hour, clock, sleep
        self._stamps: deque[float] = deque()

    def wait(self) -> float:
        """Block until another action is allowed. Returns seconds slept."""
        if self.max <= 0:
            return 0.0
        now = self.clock()
        while self._stamps and now - self._stamps[0] >= 3600:
            self._stamps.popleft()
        slept = 0.0
        if len(self._stamps) >= self.max:
            slept = 3600 - (now - self._stamps[0]) + 1
            self.sleep(slept)
        return slept

    def mark(self) -> None:
        self._stamps.append(self.clock())
