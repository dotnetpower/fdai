"""Replay-stable observation trace for the agent-owned architecture review loop."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
_STAGE_SEQUENCE = {stage: index for index, stage in enumerate(_STAGE_ORDER, start=1)}
_TOPIC_STAGES = {
    "object.change": (ArchitectureReviewStage.CHANGE,),
    "object.state-snapshot": (
        ArchitectureReviewStage.CONTEXT,
        ArchitectureReviewStage.EVIDENCE_BUNDLE,
    ),
    "object.anomaly": (ArchitectureReviewStage.RELIABILITY,),
    "object.cost-anomaly": (ArchitectureReviewStage.COST,),
    "object.capacity-forecast": (ArchitectureReviewStage.CAPACITY,),
    "object.chaos-experiment": (ArchitectureReviewStage.RECOVERY,),
    "object.verdict": (
        ArchitectureReviewStage.SCENARIO_BRANCH,
        ArchitectureReviewStage.DECISION_CASE,
        ArchitectureReviewStage.IMPACT_ENVELOPE,
        ArchitectureReviewStage.RECOMMENDATION,
    ),
    "object.audit-entry": (ArchitectureReviewStage.AUDIT,),
}
_SNAPSHOT_STAGE_HINTS = {
    "architecture_review_context": ArchitectureReviewStage.CONTEXT,
    "architecture_review_evidence_bundle": ArchitectureReviewStage.EVIDENCE_BUNDLE,
}
_DEFAULT_TRACE_DEADLINE = timedelta(minutes=5)
_TERMINAL_OBSERVER_STATES = frozenset({"gave_up", "halted"})


@dataclass(frozen=True, slots=True)
class _TraceContext:
    review_case_id: str
    deadline_at: datetime


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


class ArchitectureReviewTraceObserver:
    """Observe owned topic records and retain replayable ARB traces.

    This binding is observation-only. It consumes accountable event-bus records,
    derives a provisional per-correlation review scope, and replays the
    immutable trace projection without granting mutation or execution
    authority. To avoid overclaiming, it only starts a trace from a planned
    ``object.change`` or from an explicit ``architecture_review_trace`` hint,
    and it holds open any stage whose owned topic record is absent.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        default_deadline: timedelta = _DEFAULT_TRACE_DEADLINE,
        max_traces: int = 256,
        max_events_per_trace: int = 48,
    ) -> None:
        if default_deadline <= timedelta(0):
            raise ValueError("architecture review trace default_deadline MUST be positive")
        if max_traces < 1:
            raise ValueError("architecture review trace max_traces MUST be positive")
        if max_events_per_trace < len(_STAGE_ORDER):
            raise ValueError("architecture review trace max_events_per_trace MUST fit every stage")
        self._clock = clock or _utc_now
        self._default_deadline = default_deadline
        self._max_traces = max_traces
        self._max_events_per_trace = max_events_per_trace
        self._contexts: OrderedDict[str, _TraceContext] = OrderedDict()
        self._events: dict[tuple[str, str], list[ArchitectureReviewTraceEvent]] = {}
        self._traces: dict[tuple[str, str], ArchitectureReviewObservationTrace] = {}
        self._extra_reasons: dict[tuple[str, str], set[str]] = {}
        self._degraded_topics: dict[str, str] = {}

    def observe(
        self,
        topic: str,
        payload: Mapping[str, object],
    ) -> ArchitectureReviewObservationTrace | None:
        """Observe one owned topic record and replay its ARB trace if relevant."""

        correlation_id = _non_empty_string(payload.get("correlation_id"))
        if correlation_id is None:
            return None
        stage = self._infer_stage(topic, payload, correlation_id)
        if stage is None:
            return None
        context = self._resolve_context(
            correlation_id=correlation_id,
            stage=stage,
            topic=topic,
            payload=payload,
        )
        if context is None:
            return None
        key = (correlation_id, context.review_case_id)
        explicit_deadline = _deadline_hint(payload)
        if explicit_deadline is not None and explicit_deadline != context.deadline_at:
            self._extra_reasons.setdefault(key, set()).add(f"deadline_mismatch:{stage.value}")
        event = ArchitectureReviewTraceEvent(
            sequence=_STAGE_SEQUENCE[stage],
            stage=stage,
            topic=topic,
            producer_principal=str(payload.get("producer_principal") or ""),
            correlation_id=correlation_id,
            review_case_id=_review_case_id_hint(payload) or context.review_case_id,
            idempotency_key=_event_idempotency_key(topic, payload),
            observed_at=_observed_at(payload, clock=self._clock),
            evidence_digest=_payload_evidence_digest(payload),
            status="conformant" if stage is ArchitectureReviewStage.RECOMMENDATION else "complete",
        )
        events = self._events.setdefault(key, [])
        events.append(event)
        if len(events) > self._max_events_per_trace:
            del events[: len(events) - self._max_events_per_trace]
        self._traces[key] = self._replay(key)
        return self._traces[key]

    def observe_consumer_state(self, *, topic: str, state: str) -> None:
        """Retain terminal observer degradation for ARB-relevant topics."""

        if topic not in _TOPIC_STAGES or state not in _TERMINAL_OBSERVER_STATES:
            return
        self._degraded_topics[topic] = state
        for key in tuple(self._traces):
            self._traces[key] = self._replay(key)

    def trace_for(
        self,
        correlation_id: str,
        *,
        review_case_id: str | None = None,
    ) -> ArchitectureReviewObservationTrace | None:
        """Return the latest retained trace for one correlation."""

        context = self._contexts.get(correlation_id)
        if context is None:
            return None
        resolved_review_case = review_case_id or context.review_case_id
        return self._traces.get((correlation_id, resolved_review_case))

    def snapshot(self) -> dict[str, object]:
        """Return a bounded summary of retained ARB observation state."""

        conformant = sum(1 for trace in self._traces.values() if trace.outcome == "conformant")
        return {
            "retained_traces": len(self._traces),
            "seeded_correlations": len(self._contexts),
            "conformant_traces": conformant,
            "held_traces": len(self._traces) - conformant,
            "degraded_topics": dict(sorted(self._degraded_topics.items())),
        }

    def _infer_stage(
        self,
        topic: str,
        payload: Mapping[str, object],
        correlation_id: str,
    ) -> ArchitectureReviewStage | None:
        if (hint := _stage_hint(payload)) is not None:
            if hint is ArchitectureReviewStage.RECOMMENDATION and not _is_conformant_recommendation(
                payload
            ):
                return None
            return hint
        if topic == "object.change":
            intent_kind = str(payload.get("intent_kind") or "")
            return ArchitectureReviewStage.CHANGE if intent_kind == "planned" else None
        if topic == "object.state-snapshot":
            snapshot_type = str(payload.get("snapshot_type") or payload.get("kind") or "")
            return _SNAPSHOT_STAGE_HINTS.get(snapshot_type)
        if correlation_id not in self._contexts and _review_case_id_hint(payload) is None:
            return None
        if topic == "object.anomaly":
            return ArchitectureReviewStage.RELIABILITY
        if topic == "object.cost-anomaly":
            return ArchitectureReviewStage.COST
        if topic == "object.capacity-forecast":
            return ArchitectureReviewStage.CAPACITY
        if topic == "object.chaos-experiment":
            return ArchitectureReviewStage.RECOVERY
        if topic == "object.verdict":
            if isinstance(payload.get("decision_case"), Mapping):
                return ArchitectureReviewStage.DECISION_CASE
            if "change_assessment" in payload or "operational_context" in payload:
                return ArchitectureReviewStage.SCENARIO_BRANCH
            return None
        if topic == "object.audit-entry" and payload.get("audited_topic") == "object.verdict":
            return ArchitectureReviewStage.AUDIT
        return None

    def _resolve_context(
        self,
        *,
        correlation_id: str,
        stage: ArchitectureReviewStage,
        topic: str,
        payload: Mapping[str, object],
    ) -> _TraceContext | None:
        context = self._contexts.get(correlation_id)
        if context is not None:
            self._contexts.move_to_end(correlation_id)
            return context
        review_case_id = _review_case_id_hint(payload)
        if review_case_id is None and stage is ArchitectureReviewStage.CHANGE:
            review_case_id = _non_empty_string(payload.get("id"))
        if review_case_id is None:
            return None
        deadline_at = _deadline_hint(payload)
        if deadline_at is None:
            observed_at = _observed_at(payload, clock=self._clock)
            deadline_at = (
                _timestamp_from_value(payload.get("occurred_at"))
                if topic == "object.change"
                else observed_at
            )
            if deadline_at is None:
                deadline_at = observed_at
            deadline_at = deadline_at + self._default_deadline
        context = _TraceContext(review_case_id=review_case_id, deadline_at=deadline_at)
        self._contexts[correlation_id] = context
        self._contexts.move_to_end(correlation_id)
        while len(self._contexts) > self._max_traces:
            oldest_correlation, oldest_context = self._contexts.popitem(last=False)
            oldest_key = (oldest_correlation, oldest_context.review_case_id)
            self._events.pop(oldest_key, None)
            self._traces.pop(oldest_key, None)
            self._extra_reasons.pop(oldest_key, None)
        return context

    def _replay(self, key: tuple[str, str]) -> ArchitectureReviewObservationTrace:
        context = self._contexts.get(key[0])
        if context is None or context.review_case_id != key[1]:
            raise KeyError("architecture review trace context is unavailable")
        replayed = replay_architecture_review_trace(
            correlation_id=key[0],
            review_case_id=key[1],
            deadline_at=context.deadline_at,
            events=tuple(self._events.get(key, ())),
        )
        reasons = set(replayed.hold_reasons)
        reasons.update(self._extra_reasons.get(key, ()))
        reasons.update(self._degradation_reasons(replayed))
        hold_reasons = tuple(sorted(reasons))
        if hold_reasons == replayed.hold_reasons:
            return replayed
        return _build_trace(
            correlation_id=replayed.correlation_id,
            review_case_id=replayed.review_case_id,
            deadline_at=replayed.deadline_at,
            events=replayed.events,
            hold_reasons=hold_reasons,
        )

    def _degradation_reasons(
        self,
        trace: ArchitectureReviewObservationTrace,
    ) -> tuple[str, ...]:
        observed_stages = {event.stage for event in trace.events}
        reasons = {
            f"topic_degraded:{topic}:{state}"
            for topic, state in self._degraded_topics.items()
            if any(stage not in observed_stages for stage in _TOPIC_STAGES.get(topic, ()))
        }
        return tuple(sorted(reasons))


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

    return _build_trace(
        correlation_id=correlation_id,
        review_case_id=review_case_id,
        deadline_at=deadline_at,
        events=canonical,
        hold_reasons=tuple(sorted(reasons)),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _build_trace(
    *,
    correlation_id: str,
    review_case_id: str,
    deadline_at: datetime,
    events: tuple[ArchitectureReviewTraceEvent, ...],
    hold_reasons: tuple[str, ...],
) -> ArchitectureReviewObservationTrace:
    outcome: Literal["conformant", "hold"] = "hold" if hold_reasons else "conformant"
    material = {
        "authority_state": "observation_only",
        "correlation_id": correlation_id,
        "deadline_at": deadline_at.isoformat(),
        "events": [event.to_mapping() for event in events],
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
        events=events,
        trace_digest=_digest(material),
    )


def _stage_hint(payload: Mapping[str, object]) -> ArchitectureReviewStage | None:
    trace = payload.get("architecture_review_trace")
    if not isinstance(trace, Mapping):
        return None
    stage = trace.get("stage")
    if not isinstance(stage, str) or not stage.strip():
        return None
    try:
        return ArchitectureReviewStage(stage)
    except ValueError:
        return None


def _review_case_id_hint(payload: Mapping[str, object]) -> str | None:
    trace = payload.get("architecture_review_trace")
    trace_review_case_id = trace.get("review_case_id") if isinstance(trace, Mapping) else None
    for value in (
        payload.get("review_case_id"),
        payload.get("review_id"),
        trace_review_case_id,
    ):
        resolved = _non_empty_string(value)
        if resolved is not None:
            return resolved
    return None


def _deadline_hint(payload: Mapping[str, object]) -> datetime | None:
    trace = payload.get("architecture_review_trace")
    if isinstance(trace, Mapping):
        deadline = _timestamp_from_value(trace.get("deadline_at"))
        if deadline is not None:
            return deadline
    return _timestamp_from_value(payload.get("deadline_at"))


def _observed_at(
    payload: Mapping[str, object],
    *,
    clock: Callable[[], datetime],
) -> datetime:
    for field_name in (
        "observed_at",
        "occurred_at",
        "recorded_at",
        "closed_at",
        "updated_at",
        "ts",
    ):
        if (parsed := _timestamp_from_value(payload.get(field_name))) is not None:
            return parsed
    return clock()


def _event_idempotency_key(topic: str, payload: Mapping[str, object]) -> str:
    explicit = _non_empty_string(payload.get("idempotency_key"))
    if explicit is not None:
        return explicit
    return f"{topic}:{_payload_evidence_digest(payload)}"


def _payload_evidence_digest(payload: Mapping[str, object]) -> str:
    explicit = payload.get("evidence_digest")
    if isinstance(explicit, str) and _looks_like_sha256(explicit):
        return explicit
    canonical = {
        str(key): value for key, value in payload.items() if key != "envelope_schema_version"
    }
    return _digest(canonical)


def _timestamp_from_value(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _looks_like_sha256(value: str) -> bool:
    return (
        value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _is_conformant_recommendation(payload: Mapping[str, object]) -> bool:
    risk_verdict = str(payload.get("risk_verdict") or "")
    decision = str(payload.get("decision") or payload.get("outcome") or "")
    return risk_verdict == "auto" or decision in {
        "approved",
        "conditional",
        "conformant",
        "ready",
    }


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ArchitectureReviewObservationTrace",
    "ArchitectureReviewTraceObserver",
    "ArchitectureReviewStage",
    "ArchitectureReviewTraceEvent",
    "replay_architecture_review_trace",
]
