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
from datetime import UTC, datetime
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from fdai.core.event_ingest.correlator import CorrelationResult, EventCorrelator
from fdai.shared.contracts.models import Event
from fdai.shared.contracts.validation import EventValidator

__all__ = ["CorrelationResult", "EventCorrelator", "EventIngest"]

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
    normalized = _normalize_operator_proposal(raw)
    validator.validate(normalized)
    return Event.model_validate(normalized)


def _normalize_operator_proposal(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a raw ActionProposal in the canonical Event contract.

    Only an explicit ``operator_request`` with strict boolean
    ``operator_initiated`` is normalized. Every other mapping remains unchanged
    and must already satisfy the Event schema.
    """
    value = dict(raw)
    if value.get("event_type") != "operator_request" or value.get("operator_initiated") is not True:
        return value
    idempotency_key = value.get("idempotency_key")
    initiator = value.get("initiator_principal")
    action_type = value.get("action_type")
    params = value.get("params")
    workflow_action = value.get("workflow_action")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return value
    if not isinstance(initiator, str) or not initiator:
        return value
    if not isinstance(action_type, str) or not action_type:
        return value
    if not isinstance(params, Mapping):
        return value
    if workflow_action is not None and not _valid_workflow_action(
        workflow_action,
        idempotency_key=idempotency_key,
    ):
        return value
    at = datetime.now(tz=UTC)
    event_id = uuid5(NAMESPACE_URL, f"fdai.operator-request://{idempotency_key}")
    resource_id = value.get("resource_id")
    resource_ref = resource_id if isinstance(resource_id, str) and resource_id.strip() else None
    return {
        "schema_version": "1.0.0",
        "event_id": str(event_id),
        "idempotency_key": idempotency_key,
        "correlation_id": str(value.get("correlation_id") or event_id),
        "source": "operator_console",
        "event_type": "operator_request",
        "resource_ref": resource_ref,
        "payload": {
            "operator_request": {
                "initiator_principal": initiator,
                "action_type": action_type,
                "params": dict(params),
            },
            **(
                {"workflow_action": dict(workflow_action)}
                if isinstance(workflow_action, Mapping)
                else {}
            ),
            **(
                {"scheduled_task": dict(value["scheduled_task"])}
                if isinstance(value.get("scheduled_task"), Mapping)
                else {}
            ),
            "resource": {
                "resource_id": resource_ref,
                "resource_type": value.get("resource_type"),
                "props": {},
            },
        },
        "detected_at": at.isoformat(),
        "ingested_at": at.isoformat(),
        "mode": "shadow",
    }


def _valid_workflow_action(value: object, *, idempotency_key: str) -> bool:
    if not isinstance(value, Mapping) or set(value) != {"process_id", "step_id", "proposal_ref"}:
        return False
    if any(not isinstance(value[field], str) or not value[field] for field in value):
        return False
    proposal_ref = value.get("proposal_ref")
    return isinstance(proposal_ref, str) and proposal_ref == idempotency_key
