"""Replay-safe record projection for autonomous discovery cycles."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .discovery_contracts import (
    DiscoveryCandidate,
    DiscoveryCandidateDecision,
    DiscoveryCandidateState,
    DiscoveryCycleMetrics,
    DiscoveryCycleReport,
    DiscoverySignal,
    require_digest,
)


def cycle_report_from_record(
    record: Mapping[str, Any],
    *,
    replayed: bool = False,
) -> DiscoveryCycleReport:
    """Decode one retained terminal or failed cycle report."""

    raw_decisions = record.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("persisted discovery cycle decisions are invalid")
    decisions = tuple(_decision_from_mapping(item) for item in raw_decisions)
    raw_metrics = record.get("metrics")
    metrics = None if raw_metrics is None else _metrics_from_mapping(raw_metrics)
    return DiscoveryCycleReport(
        cycle_id=str(record["cycle_id"]),
        status=str(record["status"]),
        signal_count=int(record["signal_count"]),
        decisions=decisions,
        metrics=metrics,
        replayed=replayed,
        failure_kind=(
            str(record["failure_kind"]) if record.get("failure_kind") is not None else None
        ),
    )


def decision_record(value: DiscoveryCandidateDecision) -> dict[str, object]:
    """Project one candidate decision without model text."""

    return {
        "candidate_digest": value.candidate_digest,
        "state": value.state.value,
        "reason": value.reason,
        "review_ref": value.review_ref,
    }


def signal_record(signal: DiscoverySignal) -> dict[str, object]:
    """Project replay identity for one observed signal without source facts."""

    return {
        "signal_id": signal.signal_id,
        "kind": signal.kind.value,
        "observed_at": signal.observed_at.astimezone(UTC).isoformat(),
        "evidence_refs": list(signal.evidence_refs),
    }


def candidate_record(value: DiscoveryCandidate) -> dict[str, object]:
    """Project replay identity for one inert candidate without model text."""

    return {
        "candidate_digest": value.digest,
        "proposal_kind": value.proposal_kind,
        "target_rule_id": value.target_rule_id,
        "source_signal_ids": list(value.source_signal_ids),
    }


def cycle_audit_record(record: Mapping[str, object]) -> dict[str, object]:
    """Project one append-only lifecycle transition."""

    return {
        "schema_version": "1.0.0",
        "principal": "Norns",
        "action_kind": "rule_discovery.cycle",
        "cycle_id": record["cycle_id"],
        "schedule_id": record["schedule_id"],
        "status": record["status"],
        "stage": record["stage"],
        "revision": record["revision"],
        "grants_authority": False,
    }


def interval_bucket_start(value: datetime, interval_seconds: int) -> datetime:
    """Return the stable UTC start of the containing interval."""

    normalized = value.astimezone(UTC)
    seconds = int(normalized.timestamp())
    return datetime.fromtimestamp(seconds - (seconds % interval_seconds), tz=UTC)


def _decision_from_mapping(value: object) -> DiscoveryCandidateDecision:
    if not isinstance(value, Mapping):
        raise ValueError("persisted discovery cycle decision shape is invalid")
    candidate_digest = str(value["candidate_digest"])
    require_digest(candidate_digest, "candidate_digest")
    return DiscoveryCandidateDecision(
        candidate_digest=candidate_digest,
        state=DiscoveryCandidateState(str(value["state"])),
        reason=str(value["reason"]),
        review_ref=(str(value["review_ref"]) if value.get("review_ref") is not None else None),
    )


def _metrics_from_mapping(value: object) -> DiscoveryCycleMetrics:
    if not isinstance(value, Mapping):
        raise ValueError("persisted discovery cycle metrics are invalid")
    return DiscoveryCycleMetrics(
        candidates_per_cycle=int(value["candidates_per_cycle"]),
        gate_pass_rate=float(value["gate_pass_rate"]),
        override_trigger_rate=float(value["override_trigger_rate"]),
        retirement_rate=float(value["retirement_rate"]),
    )


__all__ = [
    "candidate_record",
    "cycle_audit_record",
    "cycle_report_from_record",
    "decision_record",
    "interval_bucket_start",
    "signal_record",
]
