"""Idempotency store - durable exactly-once guard for the executor.

The executor keeps an in-process L1 cache (`_dedupe`) so a re-delivery
this process already saw short-circuits fast. That cache is lost on
restart, so an at-least-once broker that re-delivers an event after a
restart would re-execute the mutation. This Protocol is the durable L2
guard: it records the result of a *mutating* action keyed by
``idempotency_key`` so a post-restart retry returns the prior result
instead of mutating again.

Only mutating outcomes are recorded - abstains and refusals do not
mutate, so re-evaluating them on retry is harmless and avoids write
amplification. The narrow window between "mutation applied" and "result
recorded" is closed by the transactional outbox (a separate seam); this
store closes the much larger "process restarted" window.

Async by contract - a durable backend is I/O-bound (a Postgres row with
a UNIQUE key). The in-memory implementation satisfies the same shape
with no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IdempotencyStore(Protocol):
    """Durable key -> result-payload map for mutating actions."""

    async def seen(self, key: str) -> Mapping[str, Any] | None:
        """Return the recorded result payload for ``key`` or ``None``."""
        ...

    async def record(self, key: str, result: Mapping[str, Any]) -> bool:
        """Record ``result`` under ``key``.

        Returns ``True`` when the key was newly recorded, ``False`` when a
        concurrent writer already claimed it (the caller then treats the
        action as a duplicate). Implementations MUST make this atomic
        (e.g. ``INSERT ... ON CONFLICT DO NOTHING``) so two racing
        replicas cannot both record the same key.
        """
        ...


__all__ = ["IdempotencyStore"]
