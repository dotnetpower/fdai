"""What-if replay - re-evaluate a past event under alternate rules.

Given an audit-log correlation id and a proposed rule catalog (the
"what-if" catalog), reconstructs the original event payload and asks
"what would the T0 engine have decided if THIS catalog had been loaded
when the event arrived?" - without touching any real state.

The module is a **pure sandbox**:

- MUST NOT publish any Kafka event.
- MUST NOT open a remediation PR.
- MUST NOT persist to the audit log.
- MUST NOT call any :class:`~fdai.core.executor.ShadowExecutor`.

The sandbox is an isolated
:class:`~fdai.core.tiers.t0_deterministic.T0Engine` built from the
supplied "what-if" catalog plus a snapshot evaluator. The caller wraps
the returned :class:`WhatIfReplayReport` with a UI diff of the original
audit decision vs the what-if decision.

Scope of this skeleton
----------------------
The primitives (event reconstruction, what-if catalog builder, replay
report) ship here. Full pipeline replay (trust router -> T0 -> risk
gate -> executor decision) is a natural next step but requires
wiring the risk-gate simulator too; today the skeleton exercises the
T0 layer only, which covers the "did this rule fire" question that is
the primary what-if use case.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from fdai.core.audit.rule_fire_trace import AuditItemLike


@dataclass(frozen=True, slots=True)
class ReconstructedEvent:
    """Event payload rebuilt from the audit trail."""

    correlation_id: str
    resource_id: str
    resource_type: str
    props: Mapping[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "props": dict(self.props),
        }


class EventReconstructionError(LookupError):
    """Raised when the audit trail does not carry enough to rebuild the event."""


def reconstruct_event(correlation_id: str, items: Sequence[AuditItemLike]) -> ReconstructedEvent:
    """Pull the earliest audit item's ``payload.resource`` block.

    The first audit entry for a correlation id is (by convention) the
    ``event_ingest`` stage, which records the normalized event payload.
    Missing / malformed payloads raise :class:`EventReconstructionError`.
    """
    if not items:
        raise EventReconstructionError(f"no audit items for correlation_id {correlation_id!r}")
    sorted_items = sorted(items, key=lambda i: i.seq)
    first = sorted_items[0]
    entry = dict(first.entry)
    payload = entry.get("payload") or entry.get("event_payload") or {}
    if not isinstance(payload, Mapping):
        raise EventReconstructionError("payload MUST be a mapping")
    resource = payload.get("resource")
    if not isinstance(resource, Mapping):
        raise EventReconstructionError("payload.resource MUST be a mapping")
    resource_id = str(resource.get("resource_id") or resource.get("id") or "")
    resource_type = str(resource.get("type") or "")
    props = resource.get("props") or {}
    if not resource_id or not resource_type or not isinstance(props, Mapping):
        raise EventReconstructionError("payload.resource MUST contain resource_id, type, and props")
    return ReconstructedEvent(
        correlation_id=correlation_id,
        resource_id=resource_id,
        resource_type=resource_type,
        props=dict(props),
    )


@runtime_checkable
class WhatIfEvaluator(Protocol):
    """Injected read-only evaluator (typically a fresh T0Engine per replay).

    A fork wires whatever combination of Rego evaluator + catalog it
    wants to test; the sandbox only requires that the evaluator
    returns a serialisable verdict dict per matched rule.
    """

    def evaluate(
        self, resource_type: str, resource_props: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        """Return a list of ``{rule_id, denied, reason?}`` dicts, one per rule matched."""
        ...


@dataclass(frozen=True, slots=True)
class WhatIfReplayReport:
    """Result of one what-if replay."""

    event: ReconstructedEvent
    matched_rules: tuple[Mapping[str, Any], ...]
    original_action_kinds: tuple[str, ...]
    """Distinct ``action_kind`` values observed in the original audit
    entries; the caller compares these to ``matched_rules`` to answer
    'did the what-if catalog do the same thing?'."""

    def as_json(self) -> dict[str, Any]:
        return {
            "event": self.event.as_json(),
            "matched_rules": [dict(m) for m in self.matched_rules],
            "original_action_kinds": list(self.original_action_kinds),
        }


def replay_with_what_if(
    correlation_id: str,
    items: Sequence[AuditItemLike],
    evaluator: WhatIfEvaluator,
) -> WhatIfReplayReport:
    """Reconstruct the event and evaluate it against ``evaluator``.

    The audit items feed BOTH the event reconstruction and the
    original-action-kind diff, so the caller can render a side-by-side
    "original vs what-if" table without a second query.
    """
    event = reconstruct_event(correlation_id, items)
    matched = list(evaluator.evaluate(event.resource_type, event.props))
    original_kinds = tuple(sorted({item.action_kind for item in items}))
    return WhatIfReplayReport(
        event=event,
        matched_rules=tuple(matched),
        original_action_kinds=original_kinds,
    )


__all__ = [
    "EventReconstructionError",
    "ReconstructedEvent",
    "WhatIfEvaluator",
    "WhatIfReplayReport",
    "reconstruct_event",
    "replay_with_what_if",
]
