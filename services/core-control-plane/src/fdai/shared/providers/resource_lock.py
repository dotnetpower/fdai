"""Resource lock - per-resource serialization seam.

The executor serializes actions that mutate the same resource (the
per-resource ordering rule in
``architecture.instructions.md § Idempotency, Ordering, and Replay``).
The in-process default (:class:`fdai.core.executor.lock.ResourceLockManager`)
is correct for a single replica, but the control plane is event-driven +
scale-to-zero: under KEDA more than one replica can consume the same
partition, and an in-memory lock cannot serialize across replicas. This
Protocol is the seam that lets the composition root bind a *distributed*
lock (Postgres advisory lock) so per-resource mutual exclusion holds
across the whole deployment, not just within one process.

Async by contract - a distributed backend acquires the lock over I/O
(a Postgres session advisory lock), which would otherwise block the event
loop. The in-process implementation satisfies the same async-context
shape with no I/O.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class ResourceLock(Protocol):
    """Serialize critical sections per ``resource_id``.

    ``acquire`` returns an async context manager held for the *duration
    of the action* (render + apply + audit), so a racing action on the
    same resource - in this process or another replica - waits. The lock
    MUST be crash-safe: a holder that dies without releasing must not
    wedge the resource forever (a Postgres session lock is released when
    the connection drops; the in-memory lock is forgotten on restart and
    re-derived from the audit log + idempotency key).
    """

    def acquire(self, resource_id: str) -> AbstractAsyncContextManager[None]:
        """Return an async context manager holding the per-resource lock."""
        ...


__all__ = ["ResourceLock"]
