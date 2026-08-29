"""Replay-stable observation trace for the agent-owned architecture review loop."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal


class ArchitectureReviewStage(StrEnum):
    """Ordered owner boundaries in the observation-only ARB vertical slice."""

    CHANGE = "change"
    CONTEXT = "context"
    RELIABILITY = "reliability"
    COST = "cost"
    CAPACITY = "capacity"
    RECOVERY = "recovery"
    EVIDENCE_BUNDLE = "evidence_bundle"
    SCENARIO_BRANCH = "scenario_branch"
    DECISION_CASE = "decision_case"
    IMPACT_ENVELOPE = "impact_envelope"
    RECOMMENDATION = "recommendation"
    AUDIT = "audit"


_STAGE_BINDINGS = {
    ArchitectureReviewStage.CHANGE: ("object.change", "Huginn"),
    ArchitectureReviewStage.CONTEXT: ("object.state-snapshot", "Muninn"),
    ArchitectureReviewStage.RELIABILITY: ("object.anomaly", "Heimdall"),
    ArchitectureReviewStage.COST: ("object.cost-anomaly", "Njord"),
    ArchitectureReviewStage.CAPACITY: ("object.capacity-forecast", "Freyr"),
    ArchitectureReviewStage.RECOVERY: ("object.chaos-experiment", "Loki"),
    ArchitectureReviewStage.EVIDENCE_BUNDLE: ("object.state-snapshot", "Muninn"),
    ArchitectureReviewStage.SCENARIO_BRANCH: ("object.verdict", "Forseti"),
    ArchitectureReviewStage.DECISION_CASE: ("object.verdict", "Forseti"),
    ArchitectureReviewStage.IMPACT_ENVELOPE: ("object.verdict", "Forseti"),
    ArchitectureReviewStage.RECOMMENDATION: ("object.verdict", "Forseti"),
    ArchitectureReviewStage.AUDIT: ("object.audit-entry", "Saga"),
}
_STAGE_ORDER = tuple(ArchitectureReviewStage)


@dataclass(frozen=True, slots=True)
class ArchitectureReviewTraceEvent:
    """One immutable event observed at an accountable agent topic boundary."""

    sequence: int
    stage: ArchitectureReviewStage
    topic: str
    producer_principal: str
    correlation_id: str
    review_case_id: str
    idempotency_key: str
    observed_at: datetime
    evidence_digest: str
    status: Literal["complete", "conformant"]

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("architecture review trace sequence MUST be positive")
        for name, value in (
            ("topic", self.topic),
            ("producer_principal", self.producer_principal),
            ("correlation_id", self.correlation_id),
            ("review_case_id", self.review_case_id),
            ("idempotency_key", self.idempotency_key),
        ):
            if not value.strip():
                raise ValueError(f"architecture review trace {name} MUST be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("architecture review trace observed_at MUST be timezone-aware")
        if (
            not self.evidence_digest.startswith("sha256:")
            or len(self.evidence_digest) != 71
            or any(character not in "0123456789abcdef" for character in self.evidence_digest[7:])
        ):
            raise ValueError("architecture review trace evidence_digest MUST be SHA-256")
        expected_status = (
            "conformant" if self.stage is ArchitectureReviewStage.RECOMMENDATION else "complete"
        )
        if self.status != expected_status:
            raise ValueError("architecture review trace status does not match its stage")

    @property
    def event_digest(self) -> str:
        """Return the replay identity of this event."""

        return _digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return canonical event material for persistence and replay."""

        return {
            "sequence": self.sequence,
            "stage": self.stage.value,
            "topic": self.topic,
            "producer_principal": self.producer_principal,
            "correlation_id": self.correlation_id,
            "review_case_id": self.review_case_id,
            "idempotency_key": self.idempotency_key,
            "observed_at": self.observed_at.isoformat(),
            "evidence_digest": self.evidence_digest,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ArchitectureReviewObservationTrace:
    """Terminal projection of observed agent topic records, without runtime authority."""

    correlation_id: str
    review_case_id: str
    deadline_at: datetime
    outcome: Literal["conformant", "hold"]
    hold_reasons: tuple[str, ...]
    events: tuple[ArchitectureReviewTraceEvent, ...]
    trace_digest: str
    authority_state: Literal["observation_only"] = field(default="observation_only", init=False)
    mutation_authority: Literal[False] = field(default=False, init=False)
    execution_authority: Literal[False] = field(default=False, init=False)


def replay_architecture_review_trace(
    *,
    correlation_id: str,
    review_case_id: str,
    deadline_at: datetime,
    events: tuple[ArchitectureReviewTraceEvent, ...],
) -> ArchitectureReviewObservationTrace:
    """Replay delivered events into one deterministic observation-only result."""

    if not correlation_id.strip() or not review_case_id.strip():
        raise ValueError("architecture review trace identities MUST be non-empty")
    if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
        raise ValueError("architecture review trace deadline MUST be timezone-aware")

    by_sequence: dict[int, ArchitectureReviewTraceEvent] = {}
    idempotency_sequences: dict[str, int] = {}
    reasons: set[str] = set()
    for event in events:
        prior = by_sequence.get(event.sequence)
        if prior is not None:
            if prior.event_digest != event.event_digest:
                reasons.add(f"conflicting_sequence:{event.sequence}")
                by_sequence[event.sequence] = min(
                    (prior, event),
                    key=lambda item: item.event_digest,
                )
            continue
        prior_sequence = idempotency_sequences.get(event.idempotency_key)
        if prior_sequence is not None and prior_sequence != event.sequence:
            reasons.add(f"conflicting_idempotency_key:{event.idempotency_key}")
        else:
            idempotency_sequences[event.idempotency_key] = event.sequence
        by_sequence[event.sequence] = event

    canonical = tuple(by_sequence[key] for key in sorted(by_sequence))
    expected_count = len(_STAGE_ORDER)
    if tuple(event.sequence for event in canonical) != tuple(range(1, expected_count + 1)):
        reasons.add("missing_or_non_contiguous_sequence")
    for index, stage in enumerate(_STAGE_ORDER, start=1):
        observed = by_sequence.get(index)
        if observed is None:
            reasons.add(f"missing_stage:{stage.value}")
            continue
        if observed.stage is not stage:
            reasons.add(f"stage_order_mismatch:{index}")
        expected_topic, expected_producer = _STAGE_BINDINGS[stage]
        if observed.topic != expected_topic or observed.producer_principal != expected_producer:
            reasons.add(f"owner_mismatch:{stage.value}")
        if observed.correlation_id != correlation_id or observed.review_case_id != review_case_id:
            reasons.add(f"identity_mismatch:{stage.value}")
        if observed.observed_at > deadline_at:
            reasons.add(f"late_stage:{stage.value}")

    outcome: Literal["conformant", "hold"] = "hold" if reasons else "conformant"
    hold_reasons = tuple(sorted(reasons))
    material = {
        "authority_state": "observation_only",
        "correlation_id": correlation_id,
        "deadline_at": deadline_at.isoformat(),
        "events": [event.to_mapping() for event in canonical],
        "execution_authority": False,
        "hold_reasons": list(hold_reasons),
        "mutation_authority": False,
        "outcome": outcome,
        "review_case_id": review_case_id,
    }
    return ArchitectureReviewObservationTrace(
        correlation_id=correlation_id,
        review_case_id=review_case_id,
        deadline_at=deadline_at,
        outcome=outcome,
        hold_reasons=hold_reasons,
        events=canonical,
        trace_digest=_digest(material),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "ArchitectureReviewObservationTrace",
    "ArchitectureReviewStage",
    "ArchitectureReviewTraceEvent",
    "replay_architecture_review_trace",
]
