"""Bounded intake for the three initial cross-vertical action candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.forseti_decision_helpers import (
    domain_option_evidence,
    source_freshness,
)
from fdai.core.decision_case import DomainOptionEvidence
from fdai.core.operational_context import SourceFreshness

INITIAL_VERTICAL_DOMAINS: tuple[str, ...] = (
    "resilience",
    "change_safety",
    "cost",
)

_CANDIDATE_TOPIC_BINDINGS: dict[str, tuple[str, str]] = {
    "object.resilience-score": ("resilience", "Loki"),
    "object.drift": ("change_safety", "Heimdall"),
    "object.cost-anomaly": ("cost", "Njord"),
}


class CandidateIntakeState(StrEnum):
    PENDING = "pending"
    DUPLICATE = "duplicate"
    READY = "ready"
    HIL = "hil"


@dataclass(frozen=True, slots=True)
class CandidateClosure:
    correlation_id: str
    resource_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CrossVerticalCandidateBatch:
    correlation_id: str
    resource_id: str
    observed_at: str
    evidence_by_domain: dict[str, DomainOptionEvidence]
    principals_by_domain: dict[str, str]
    source_freshness: tuple[SourceFreshness, ...]

    @property
    def advice(self) -> dict[str, str]:
        return {
            domain: evidence.action_type for domain, evidence in self.evidence_by_domain.items()
        }

    @property
    def impacts(self) -> dict[str, float]:
        return {
            domain: max(abs(effect.utility) for effect in evidence.effects)
            for domain, evidence in self.evidence_by_domain.items()
        }


@dataclass(frozen=True, slots=True)
class CandidateIntake:
    state: CandidateIntakeState
    correlation_id: str
    batch: CrossVerticalCandidateBatch | None = None
    closures: tuple[CandidateClosure, ...] = ()


@dataclass(frozen=True, slots=True)
class _Candidate:
    domain: str
    principal: str
    correlation_id: str
    idempotency_key: str
    resource_id: str
    observed_at: str
    evidence: DomainOptionEvidence
    source_freshness: tuple[SourceFreshness, ...]
    digest: str


@dataclass(slots=True)
class _PendingSet:
    correlation_id: str
    resource_id: str
    observed_at: str
    candidates: dict[str, _Candidate] = field(default_factory=dict)


class CrossVerticalCandidateAccumulator:
    """Join owner-authenticated candidates without mixing resources or replays."""

    def __init__(self, *, max_pending: int = 10_000) -> None:
        self._pending: BoundedLruDict[str, _PendingSet] = BoundedLruDict(max_pending)
        self._active_by_resource: BoundedLruDict[str, str] = BoundedLruDict(max_pending)
        self._completed: BoundedLruSet[str] = BoundedLruSet(max_pending)

    def ingest(self, topic: str, payload: dict[str, Any]) -> CandidateIntake:
        candidate = _parse_candidate(topic, payload)
        correlation_id = candidate.correlation_id
        if correlation_id in self._completed:
            return CandidateIntake(CandidateIntakeState.DUPLICATE, correlation_id)

        active = self._active_by_resource.get(candidate.resource_id)
        if active is not None and active != correlation_id:
            prior = self._pending.pop(active)
            self._active_by_resource.pop(candidate.resource_id, None)
            self._completed.add(active)
            self._completed.add(correlation_id)
            closures = [
                CandidateClosure(
                    correlation_id=correlation_id,
                    resource_id=candidate.resource_id,
                    reason="cross_vertical_concurrent_set",
                )
            ]
            if prior is not None:
                closures.insert(
                    0,
                    CandidateClosure(
                        correlation_id=prior.correlation_id,
                        resource_id=prior.resource_id,
                        reason="cross_vertical_concurrent_set",
                    ),
                )
            return CandidateIntake(
                CandidateIntakeState.HIL,
                correlation_id,
                closures=tuple(closures),
            )

        pending = self._pending.get(correlation_id)
        if pending is None:
            pending = _PendingSet(
                correlation_id=correlation_id,
                resource_id=candidate.resource_id,
                observed_at=candidate.observed_at,
            )
            self._pending.set(correlation_id, pending)
            self._active_by_resource.set(candidate.resource_id, correlation_id)
        elif (
            pending.resource_id != candidate.resource_id
            or pending.observed_at != candidate.observed_at
        ):
            return self._close(
                pending,
                reason="cross_vertical_candidate_identity_conflict",
                extra_correlation=correlation_id,
            )

        existing = pending.candidates.get(candidate.domain)
        if existing is not None:
            if (
                existing.idempotency_key == candidate.idempotency_key
                and existing.digest == candidate.digest
            ):
                return CandidateIntake(CandidateIntakeState.DUPLICATE, correlation_id)
            return self._close(
                pending,
                reason="cross_vertical_candidate_replay_conflict",
            )

        pending.candidates[candidate.domain] = candidate
        if set(pending.candidates) != set(INITIAL_VERTICAL_DOMAINS):
            return CandidateIntake(CandidateIntakeState.PENDING, correlation_id)

        self._pending.pop(correlation_id, None)
        self._active_by_resource.pop(candidate.resource_id, None)
        self._completed.add(correlation_id)
        ordered = tuple(pending.candidates[domain] for domain in INITIAL_VERTICAL_DOMAINS)
        freshness = tuple(
            dict.fromkeys(
                item for candidate_item in ordered for item in candidate_item.source_freshness
            )
        )
        return CandidateIntake(
            CandidateIntakeState.READY,
            correlation_id,
            batch=CrossVerticalCandidateBatch(
                correlation_id=correlation_id,
                resource_id=candidate.resource_id,
                observed_at=candidate.observed_at,
                evidence_by_domain={item.domain: item.evidence for item in ordered},
                principals_by_domain={item.domain: item.principal for item in ordered},
                source_freshness=freshness,
            ),
        )

    def expire(self, correlation_id: str) -> CandidateClosure | None:
        pending = self._pending.pop(correlation_id, None)
        if pending is None:
            return None
        self._active_by_resource.pop(pending.resource_id, None)
        self._completed.add(correlation_id)
        return CandidateClosure(
            correlation_id=correlation_id,
            resource_id=pending.resource_id,
            reason="cross_vertical_candidate_timeout",
        )

    def _close(
        self,
        pending: _PendingSet,
        *,
        reason: str,
        extra_correlation: str | None = None,
    ) -> CandidateIntake:
        self._pending.pop(pending.correlation_id, None)
        self._active_by_resource.pop(pending.resource_id, None)
        self._completed.add(pending.correlation_id)
        if extra_correlation is not None:
            self._completed.add(extra_correlation)
        return CandidateIntake(
            CandidateIntakeState.HIL,
            extra_correlation or pending.correlation_id,
            closures=(
                CandidateClosure(
                    correlation_id=pending.correlation_id,
                    resource_id=pending.resource_id,
                    reason=reason,
                ),
            ),
        )


def is_cross_vertical_candidate(topic: str, payload: dict[str, Any]) -> bool:
    return payload.get("kind") == "cross_vertical_candidate" and topic in _CANDIDATE_TOPIC_BINDINGS


def _parse_candidate(topic: str, payload: dict[str, Any]) -> _Candidate:
    binding = _CANDIDATE_TOPIC_BINDINGS.get(topic)
    if binding is None:
        raise ValueError("cross-vertical candidate topic is not registered")
    domain, expected_principal = binding
    principal = str(payload.get("producer_principal") or "")
    if principal != expected_principal:
        raise ValueError("cross-vertical candidate principal does not own the vertical topic")

    correlation_id = str(payload.get("correlation_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    resource_id = str(payload.get("resource_id") or "")
    observed_at = str(payload.get("observed_at") or "")
    action_type = str(payload.get("action_type") or "")
    if not all((correlation_id, idempotency_key, resource_id, observed_at, action_type)):
        raise ValueError("cross-vertical candidate identities MUST be non-empty")
    for name, value, maximum in (
        ("correlation_id", correlation_id, 256),
        ("idempotency_key", idempotency_key, 512),
        ("resource_id", resource_id, 512),
        ("action_type", action_type, 160),
    ):
        if not value.strip() or value != value.strip() or len(value) > maximum:
            raise ValueError(f"cross-vertical candidate {name} is not a bounded identifier")
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("cross-vertical candidate observed_at is invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("cross-vertical candidate observed_at MUST include timezone")

    evidence = domain_option_evidence(
        [
            {
                "domain": domain,
                "action_type": action_type,
                "effects": payload.get("effects"),
                "evidence_refs": payload.get("evidence_refs"),
            }
        ]
    )[0]
    freshness = source_freshness(payload.get("source_freshness"))
    normalized = {
        "domain": domain,
        "principal": principal,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "resource_id": resource_id,
        "observed_at": observed_at,
        "action_type": action_type,
        "effects": payload.get("effects"),
        "evidence_refs": payload.get("evidence_refs"),
        "source_freshness": payload.get("source_freshness"),
    }
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return _Candidate(
        domain=domain,
        principal=principal,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        resource_id=resource_id,
        observed_at=observed_at,
        evidence=evidence,
        source_freshness=freshness,
        digest=digest,
    )


__all__ = [
    "CandidateClosure",
    "CandidateIntake",
    "CandidateIntakeState",
    "CrossVerticalCandidateAccumulator",
    "CrossVerticalCandidateBatch",
    "INITIAL_VERTICAL_DOMAINS",
    "is_cross_vertical_candidate",
]
