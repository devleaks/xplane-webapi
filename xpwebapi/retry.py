"""Retry helpers for transient X-Plane connection probes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for exponential backoff retries."""

    attempts: int = 1
    backoff: float = 0.0
    max_backoff: float = 5.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", max(1, int(self.attempts)))
        object.__setattr__(self, "backoff", max(0.0, float(self.backoff)))
        object.__setattr__(self, "max_backoff", max(0.0, float(self.max_backoff)))
        object.__setattr__(self, "multiplier", max(1.0, float(self.multiplier)))

    def delay(self, failure_index: int) -> float:
        """Return the delay after a failed attempt."""
        if self.backoff == 0.0:
            return 0.0
        return min(self.backoff * (self.multiplier**failure_index), self.max_backoff)


def sleep_before_retry(config: RetryConfig, failure_index: int, sleeper: Callable[[float], None] = time.sleep) -> None:
    """Sleep for the configured backoff delay if one is configured."""
    delay = config.delay(failure_index)
    if delay > 0.0:
        sleeper(delay)


async def async_sleep_before_retry(config: RetryConfig, failure_index: int) -> None:
    """Async equivalent of sleep_before_retry."""
    delay = config.delay(failure_index)
    if delay > 0.0:
        await asyncio.sleep(delay)
