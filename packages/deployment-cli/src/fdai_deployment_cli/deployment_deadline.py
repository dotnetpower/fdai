"""Monotonic remaining-budget checks for standalone deployment stage scheduling."""

from __future__ import annotations

import time
from collections.abc import Callable


class DeploymentDeadline:
    """Keep one invocation budget; expiry cannot authorize another stage or ready receipt.

    This scheduler guard does not interrupt a running command. Callers pass its current
    remaining budget to their bounded process or transport and preserve its cleanup path.
    """

    def __init__(self, seconds: int, *, clock: Callable[[], float] | None = None) -> None:
        if type(seconds) is not int or seconds <= 0:
            raise ValueError("standalone deployment timeout must be a positive integer")
        self._clock = clock or time.monotonic
        self._expires = self._clock() + seconds

    def remaining(self, maximum: int | None = None) -> int:
        """Return whole seconds left, capped by the stage limit, or stop on expiry."""

        remaining = int(self._expires - self._clock())
        if remaining <= 0:
            raise TimeoutError("standalone deployment deadline has no remaining budget")
        return remaining if maximum is None else min(maximum, remaining)
