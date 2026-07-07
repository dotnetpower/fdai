"""Bus consumers.

Normalize to the event schema, deduplicate by idempotency key, and correlate
related events into incidents.

P1 W-3 Step 3f scope
--------------------

This module ships the two duties the T0 pipeline needs today:

- **Normalize** - accept a raw payload (already-validated ``Event`` or a
  dict destined for the event schema) and return a typed
  :class:`~fdai.shared.contracts.models.Event` model. Enforcing
  the schema at the ingress boundary is the only place where untrusted
  input meets the type system; downstream code can trust it.
- **Deduplicate** - reject a second delivery of the same
  ``idempotency_key`` by returning :data:`None`. The cache is a bounded
  in-process FIFO (``max_entries`` on :class:`EventIngest`,
  default 50 000) so a runaway ingest cannot exhaust memory; the
  executor's own ``Action.idempotency_key`` guard is the durable stop.
  A Kafka consumer group + persistent dedupe cache lands with W-4.

Correlation-into-incidents is Phase 2 (T1 similarity work); the seam is
declared here so a follow-up wires it without changing the interface.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Final

from fdai.shared.contracts.models import Event
from fdai.shared.contracts.validation import EventValidator

__all__ = ["EventIngest"]

# Default bound on the in-process dedupe cache. Guards against unbounded
# growth in a long-running process while staying deep enough to cover a
# realistic Kafka consumer's re-delivery window (Event Hubs default
# checkpoint interval is 5s; at 200 events/s that is 1k in-flight
# entries, so 50k gives >4 minutes of history). Persistent dedupe lands
# with W-4 (see the module docstring).
_DEFAULT_MAX_ENTRIES: Final[int] = 50_000


class EventIngest:
    """Normalize + deduplicate incoming events.

    Wraps an :class:`EventValidator` (JSON Schema + pydantic) plus a
    bounded FIFO dedupe cache keyed on ``idempotency_key``. When the
    cache is full, the oldest entry is evicted - a subsequent
    re-delivery of an evicted key is treated as a fresh event (fail
    forward: the downstream executor's own idempotency guard
    (:attr:`Action.idempotency_key`) is the durable stop, not this
    in-process cache).
    """

    def __init__(
        self,
        *,
        validator: EventValidator,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries MUST be >= 1")
        self._validator = validator
        self._max_entries = max_entries
        # OrderedDict acts as an insertion-ordered FIFO: `move_to_end` is
        # NOT used because a re-delivery MUST return None (deduped) and
        # MUST NOT extend the entry's lifetime; the cache is a bounded
        # window of "recently accepted" keys.
        self._seen: OrderedDict[str, None] = OrderedDict()

    def ingest(self, raw: Event | Mapping[str, Any]) -> Event | None:
        """Return a typed :class:`Event` or ``None`` for a duplicate.

        Never raises for a duplicate - a re-delivery is a valid runtime
        state, not an error. Schema-invalid input raises whatever the
        validator raises (typically a schema error propagated up), so
        the caller can audit the failure at the ingress boundary.
        """
        event = _coerce(raw, validator=self._validator)
        key = event.idempotency_key
        if key in self._seen:
            return None
        self._seen[key] = None
        if len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return event

    def seen_keys(self) -> frozenset[str]:
        """Return the set of idempotency keys currently in the bounded cache."""
        return frozenset(self._seen)


def _coerce(raw: Event | Mapping[str, Any], *, validator: EventValidator) -> Event:
    if isinstance(raw, Event):
        return raw
    validator.validate(dict(raw))
    return Event.model_validate(dict(raw))
