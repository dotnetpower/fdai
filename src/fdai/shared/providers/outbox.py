"""Transactional outbox - claim-before-mutation exactly-once guard.

The idempotency store (:mod:`fdai.shared.providers.idempotency`) records a
result *after* a mutation, so a crash between "mutation applied" and
"result recorded" can still re-mutate on retry. The outbox closes that
window by recording *intent* durably **before** the mutation:

1. ``claim(key)`` atomically writes an ``in_progress`` row and returns
   whether this is the first attempt (``NEW``), a retry of an unfinished
   attempt (``IN_PROGRESS`` - a prior process claimed it but crashed
   before completing), or an already-``DONE`` action (the recorded
   result is returned and the mutation is skipped).
2. The caller performs the (idempotent) mutation.
3. ``complete(key, result)`` marks the row done and stores the result.

Combined with an idempotent mutation (PR-native reuses the same branch;
a direct-API adapter dedups on its own ledger), this yields exactly-once
effect: the intent survives a crash (no lost action) and a retry re-runs
the idempotent mutation to completion (no double effect).

Async by contract - a durable backend is I/O-bound (a Postgres row). The
in-memory implementation satisfies the same shape with no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class OutboxStatus(StrEnum):
    """Result of a :meth:`OutboxStore.claim`."""

    NEW = "new"
    """First claim - proceed to mutate."""

    IN_PROGRESS = "in_progress"
    """A prior claim exists but never completed (crash mid-flight or a
    concurrent attempt). The caller re-runs the idempotent mutation."""

    DONE = "done"
    """The action already completed; :attr:`OutboxClaim.result` holds the
    recorded result and the mutation MUST be skipped."""


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    status: OutboxStatus
    result: Mapping[str, Any] | None = None


@runtime_checkable
class OutboxStore(Protocol):
    """Durable intent log claimed before a mutation, completed after."""

    async def claim(self, key: str) -> OutboxClaim:
        """Atomically claim ``key`` for mutation.

        Implementations MUST make the first-writer decision atomic (e.g.
        ``INSERT ... ON CONFLICT``) so two racing replicas cannot both get
        ``NEW`` for the same key.
        """
        ...

    async def complete(self, key: str, result: Mapping[str, Any]) -> None:
        """Mark ``key`` done and store ``result`` for future claims."""
        ...


__all__ = ["OutboxStore", "OutboxStatus", "OutboxClaim"]
