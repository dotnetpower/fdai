"""Rule-fire trace reconstruction from the audit log.

Given a ``correlation_id``, walk the audit log and assemble the full
end-to-end trace of what happened for that event:

    event ingest -> trust router -> tier (T0/T1/T2) -> quality gate ->
    risk gate -> executor -> delivery

Each stage lands as one :class:`RuleFireTraceStep` on the trace; the
reader is Protocol-typed so a fork can plug in any backing store
(shipped Operator API model, Postgres direct, Log Analytics).

Placement invariant
-------------------
``core/`` MUST NOT depend on ``delivery/``, so this module works with
the minimal :class:`AuditItemLike` Protocol below rather than the
delivery-side ``AuditItem`` dataclass. The reference delivery-side
reader lives at
:mod:`fdai.delivery.operator_api.rule_fire_trace_reader` where the
concrete dependency is legal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AuditItemLike(Protocol):
    """Structural shape the trace builder needs from any audit item.

    Kept minimal (six attributes) so any audit-store adapter can adapt
    its native row into this shape without a heavyweight conversion.
    """

    seq: int
    correlation_id: str | None
    entry: Mapping[str, Any]
    action_kind: str
    mode: str
    entry_hash: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RuleFireTraceStep:
    """One stage in the reconstructed trace."""

    seq: int
    recorded_at: str
    stage: str | None
    """PipelineStage value from the audit entry (``L1_evaluate``,
    ``remediate``, ``escalate``, ...), or ``None`` when the source
    entry records correlated activity without a pipeline stage."""
    decision: str | None
    reason: str | None
    action_kind: str
    mode: str
    entry_hash: str

    @classmethod
    def from_audit_item(cls, item: AuditItemLike) -> RuleFireTraceStep:
        entry = dict(item.entry)
        stage = _extract_string(entry, "pipeline_stage") or _extract_string(entry, "stage")
        decision = _extract_string(entry, "decision")
        reason = _extract_string(entry, "reason") or _extract_string(entry, "deny_reason")
        return cls(
            seq=item.seq,
            recorded_at=item.recorded_at,
            stage=stage,
            decision=decision,
            reason=reason,
            action_kind=item.action_kind,
            mode=item.mode,
            entry_hash=item.entry_hash,
        )


@dataclass(frozen=True, slots=True)
class RuleFireTrace:
    """The full ordered trace for one ``correlation_id``."""

    correlation_id: str
    steps: tuple[RuleFireTraceStep, ...]

    def as_json(self) -> dict[str, Any]:
        terminal_stage = next(
            (step.stage for step in reversed(self.steps) if step.stage is not None),
            None,
        )
        return {
            "correlation_id": self.correlation_id,
            "step_count": len(self.steps),
            "steps": [
                {
                    "seq": step.seq,
                    "recorded_at": step.recorded_at,
                    "stage": step.stage,
                    "decision": step.decision,
                    "reason": step.reason,
                    "action_kind": step.action_kind,
                    "mode": step.mode,
                    "entry_hash": step.entry_hash,
                }
                for step in self.steps
            ],
            "terminal_stage": terminal_stage,
        }


@runtime_checkable
class AuditTraceReader(Protocol):
    """Fork-injected read seam that returns the audit items for a correlation."""

    async def read_items(self, correlation_id: str) -> Sequence[AuditItemLike]:
        """Return every audit item that shares ``correlation_id``, oldest first."""
        ...


def build_rule_fire_trace(
    correlation_id: str, items: Iterable[AuditItemLike]
) -> RuleFireTrace | None:
    """Turn a sequence of audit items into a :class:`RuleFireTrace`.

    Returns ``None`` when no items match the correlation, so the
    caller can surface a clean 404. Items ARE assumed to already share
    the same ``correlation_id`` - the reader is the authoritative
    filter.
    """
    steps = tuple(RuleFireTraceStep.from_audit_item(item) for item in items)
    if not steps:
        return None
    return RuleFireTrace(correlation_id=correlation_id, steps=steps)


def _extract_string(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


__all__ = [
    "AuditItemLike",
    "AuditTraceReader",
    "RuleFireTrace",
    "RuleFireTraceStep",
    "build_rule_fire_trace",
]
