"""Finite polling sessions. A failed poll ends the session without an automatic retry."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PollLimits:
    max_polls: int = 30
    interval_seconds: float = 15
    max_duration_seconds: float = 900

    def __post_init__(self) -> None:
        if not 1 <= self.max_polls <= 10000:
            raise ValueError("max-polls MUST be between 1 and 10000.")
        for value in (self.interval_seconds, self.max_duration_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Polling interval and duration MUST be positive and finite.")


def poll_bounded(
    poll: Callable[[], int],
    limits: PollLimits,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Bound poll starts and sleeps. An in-flight apply completes its bounded recovery first."""
    deadline = monotonic() + limits.max_duration_seconds
    for index in range(limits.max_polls):
        if monotonic() >= deadline:
            logging.error("lifecycle_agent.polling_stopped reason=deadline")
            return 1
        result = poll()
        if result:
            return result
        if monotonic() >= deadline:
            logging.error("lifecycle_agent.polling_stopped reason=deadline")
            return 1
        if index + 1 < limits.max_polls:
            remaining = deadline - monotonic()
            if remaining <= limits.interval_seconds:
                logging.error("lifecycle_agent.polling_stopped reason=insufficient_poll_budget")
                return 1
            sleep(limits.interval_seconds)
    return 0
