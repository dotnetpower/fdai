"""Content-free correlation trace completeness for ChatOps qualification."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class CorrelationTraceStage(StrEnum):
    SESSION = "session"
    REQUEST = "request"
    TURN = "turn"
    TOOL_AGENT_EVIDENCE = "tool_agent_evidence"
    PROPOSAL = "proposal"
    DECISION = "decision"
    DELIVERY = "delivery"
    AUDIT = "audit"


class TraceTimestampAuthority(StrEnum):
    SERVICE_CLOCK = "service_clock"
    DATABASE_COMMIT = "database_commit"
    PROVIDER_RECEIPT = "provider_receipt"
    OTEL_SPAN = "otel_span"


@dataclass(frozen=True, slots=True)
class CorrelationTraceEvent:
    stage: CorrelationTraceStage
    occurred_at: str
    timestamp_authority: TraceTimestampAuthority
    correlation_digest: str
    record_digest: str
    predecessor_record_digest: str | None
    provenance_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, CorrelationTraceStage) or not isinstance(
            self.timestamp_authority, TraceTimestampAuthority
        ):
            raise ValueError("trace stage and timestamp authority MUST use contract enums")
        _timestamp(self.occurred_at, "trace occurred_at")
        _sha256(self.correlation_digest, "trace correlation_digest")
        _sha256(self.record_digest, "trace record_digest")
        if self.predecessor_record_digest is not None:
            _sha256(
                self.predecessor_record_digest,
                "trace predecessor_record_digest",
            )
        _sha256(self.provenance_digest, "trace provenance_digest")


@dataclass(frozen=True, slots=True)
class CorrelationTraceBatch:
    trace_id: str
    source_revision: str
    started_at: str
    completed_at: str
    events: tuple[CorrelationTraceEvent, ...]

    def __post_init__(self) -> None:
        _token(self.trace_id, "trace_id")
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("trace source_revision MUST be a full git object id")
        started = _timestamp(self.started_at, "trace started_at")
        completed = _timestamp(self.completed_at, "trace completed_at")
        if completed < started:
            raise ValueError("trace completed_at MUST NOT precede started_at")
        if len(self.events) > 64:
            raise ValueError("trace events MUST contain at most 64 records")
        if any(not isinstance(event, CorrelationTraceEvent) for event in self.events):
            raise ValueError("trace events MUST use CorrelationTraceEvent records")


@dataclass(frozen=True, slots=True)
class CorrelationTraceEvidence:
    trace_digest: str
    source_revision: str
    started_at: str
    completed_at: str
    correlation_digest: str | None
    event_manifest_digest: str
    stage_counts: tuple[tuple[CorrelationTraceStage, int], ...]
    timestamp_authorities: tuple[TraceTimestampAuthority, ...]
    complete_trace: bool
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "chatops_correlation_trace",
            "qualification_authority": False,
            "trace_digest": self.trace_digest,
            "source_revision": self.source_revision,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "correlation_digest": self.correlation_digest,
            "event_manifest_digest": self.event_manifest_digest,
            "stage_counts": {stage.value: count for stage, count in self.stage_counts},
            "timestamp_authorities": [authority.value for authority in self.timestamp_authorities],
            "complete_trace": self.complete_trace,
            "gaps": list(self.gaps),
        }
        payload["content_digest"] = _digest(payload)
        return payload


def reduce_correlation_trace(batch: CorrelationTraceBatch) -> CorrelationTraceEvidence:
    """Require the exact ordered stage chain without reading record payloads."""

    events = batch.events
    stage_counts = Counter(event.stage for event in events)
    gaps: list[str] = []
    missing = [stage.value for stage in CorrelationTraceStage if stage_counts[stage] == 0]
    duplicate = [stage.value for stage in CorrelationTraceStage if stage_counts[stage] > 1]
    if missing:
        gaps.append("missing_stages=" + ",".join(missing))
    if duplicate:
        gaps.append("duplicate_stages=" + ",".join(duplicate))
    if tuple(event.stage for event in events) != tuple(CorrelationTraceStage):
        gaps.append("stage_order_mismatch")

    correlations = {event.correlation_digest for event in events}
    if len(correlations) != 1:
        gaps.append("correlation_digest_mismatch")
    record_digests = tuple(event.record_digest for event in events)
    if len(record_digests) != len(set(record_digests)):
        gaps.append("duplicate_record_digest")
    for index, event in enumerate(events):
        expected_predecessor = None if index == 0 else events[index - 1].record_digest
        if event.predecessor_record_digest != expected_predecessor:
            gaps.append(f"predecessor_mismatch:{event.stage.value}")
    observed = tuple(_timestamp(event.occurred_at, "trace occurred_at") for event in events)
    if observed != tuple(sorted(observed)):
        gaps.append("timestamp_order_mismatch")
    started = _timestamp(batch.started_at, "trace started_at")
    completed = _timestamp(batch.completed_at, "trace completed_at")
    if any(timestamp < started or timestamp > completed for timestamp in observed):
        gaps.append("timestamp_outside_trace_window")

    return CorrelationTraceEvidence(
        trace_digest=_digest(batch.trace_id),
        source_revision=batch.source_revision,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        correlation_digest=next(iter(correlations)) if len(correlations) == 1 else None,
        event_manifest_digest=_event_manifest_digest(events),
        stage_counts=tuple((stage, stage_counts[stage]) for stage in CorrelationTraceStage),
        timestamp_authorities=tuple(
            authority
            for authority in TraceTimestampAuthority
            if authority in {event.timestamp_authority for event in events}
        ),
        complete_trace=not gaps,
        gaps=tuple(gaps),
    )


def _event_manifest_digest(events: tuple[CorrelationTraceEvent, ...]) -> str:
    return _digest(
        [
            {
                "stage": event.stage.value,
                "occurred_at": event.occurred_at,
                "timestamp_authority": event.timestamp_authority.value,
                "correlation_digest": event.correlation_digest,
                "record_digest": event.record_digest,
                "predecessor_record_digest": event.predecessor_record_digest,
                "provenance_digest": event.provenance_digest,
            }
            for event in events
        ]
    )


def trace_set_digest(trace_digests: tuple[str, ...]) -> str:
    """Commit to one non-empty unique set of trace identities."""

    if not trace_digests or len(trace_digests) != len(set(trace_digests)):
        raise ValueError("trace digest set MUST be non-empty and unique")
    for value in trace_digests:
        _sha256(value, "trace set digest")
    return _digest(sorted(trace_digests))


def _token(value: str, field: str) -> None:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a bounded portable token")


def _sha256(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} MUST include a timezone")
    return parsed


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


__all__ = [
    "CorrelationTraceBatch",
    "CorrelationTraceEvent",
    "CorrelationTraceEvidence",
    "CorrelationTraceStage",
    "TraceTimestampAuthority",
    "reduce_correlation_trace",
    "trace_set_digest",
]
