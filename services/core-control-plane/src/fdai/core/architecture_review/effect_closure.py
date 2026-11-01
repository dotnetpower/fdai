"""ARB-4 independent multi-effect closure and bounded Vidar recovery coordination.

Architecture Review Board (ARB) decisions remain control-only (`arb_execution_authority=False`).
When an approved change routes through the ordinary action pipeline (`ActionType` promotion,
policy, risk, Var, Thor, and Saga), this module links `Change -> DecisionCase -> ImpactEnvelope
-> ActionRun -> ObservedOutcome`, enforces independent effect observation by Heimdall (rejecting
self-scored outcomes from the executor or judge), keeps missing or incomplete observations pending,
and emits a bounded Vidar recovery request within the approved `ImpactEnvelope` when an effect
fails, a stop condition triggers, or a protected objective is violated.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

_HEX_DIGITS = frozenset("0123456789abcdef")


def _require_non_empty(name: str, value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"architecture review effect closure {name} MUST be non-empty")
    return stripped


def _require_sha256(name: str, value: str) -> str:
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(ch not in _HEX_DIGITS for ch in value[7:])
    ):
        raise ValueError(f"architecture review effect closure {name} MUST be SHA-256")
    return value


def _require_aware_datetime(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"architecture review effect closure {name} MUST be timezone-aware")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ArchitectureReviewExpectedEffect:
    """One expected post-action effect bounded by the approved ImpactEnvelope."""

    effect_id: str
    metric: str
    target_ref: str
    expected_min: float
    expected_max: float
    window_seconds: int = 300

    def __post_init__(self) -> None:
        _require_non_empty("effect_id", self.effect_id)
        _require_non_empty("metric", self.metric)
        _require_non_empty("target_ref", self.target_ref)
        if isinstance(self.expected_min, bool) or isinstance(self.expected_max, bool):
            raise ValueError("expected effect bounds MUST be numeric")
        if not (math.isfinite(self.expected_min) and math.isfinite(self.expected_max)):
            raise ValueError("expected effect bounds MUST be finite")
        if self.expected_min > self.expected_max:
            raise ValueError("expected_min MUST NOT exceed expected_max")
        if isinstance(self.window_seconds, bool) or self.window_seconds < 1:
            raise ValueError("window_seconds MUST be positive")


@dataclass(frozen=True, slots=True)
class ArchitectureReviewActionRunLink:
    """Lineage binding `Change -> DecisionCase -> ImpactEnvelope -> ActionRun`."""

    review_case_id: str
    change_id: str
    decision_case_id: str
    impact_envelope_id: str
    action_run_id: str
    selected_option_id: str
    action_type: str
    executor_principal: str
    idempotency_key: str
    target_lock_ref: str
    stop_condition_ref: str
    rollback_ref: str
    executed_at: datetime
    expected_effects: tuple[ArchitectureReviewExpectedEffect, ...]
    mode: Literal["shadow", "enforce"] = "shadow"
    arb_execution_authority: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("review_case_id", self.review_case_id),
            ("change_id", self.change_id),
            ("decision_case_id", self.decision_case_id),
            ("impact_envelope_id", self.impact_envelope_id),
            ("action_run_id", self.action_run_id),
            ("selected_option_id", self.selected_option_id),
            ("action_type", self.action_type),
            ("executor_principal", self.executor_principal),
            ("idempotency_key", self.idempotency_key),
            ("target_lock_ref", self.target_lock_ref),
            ("stop_condition_ref", self.stop_condition_ref),
            ("rollback_ref", self.rollback_ref),
        ):
            _require_non_empty(name, value)
        _require_aware_datetime("executed_at", self.executed_at)
        if self.mode not in {"shadow", "enforce"}:
            raise ValueError("mode MUST be 'shadow' or 'enforce'")
        if not self.expected_effects:
            raise ValueError("expected_effects MUST contain at least one expected effect")
        effect_ids = [effect.effect_id for effect in self.expected_effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("expected_effects MUST have unique effect_id values")


@dataclass(frozen=True, slots=True)
class ArchitectureReviewEffectObservation:
    """One authoritative post-action observation reported for an expected effect."""

    observation_id: str
    effect_id: str
    action_run_id: str
    observer_principal: str
    observed_value: float | None
    observed_at: datetime
    evidence_digest: str
    complete: bool = True
    stop_condition_triggered: bool = False
    protected_objective_violated: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("observation_id", self.observation_id),
            ("effect_id", self.effect_id),
            ("action_run_id", self.action_run_id),
            ("observer_principal", self.observer_principal),
        ):
            _require_non_empty(name, value)
        _require_aware_datetime("observed_at", self.observed_at)
        _require_sha256("evidence_digest", self.evidence_digest)
        if self.observed_value is not None:
            if isinstance(self.observed_value, bool) or not math.isfinite(self.observed_value):
                raise ValueError("observed_value MUST be a finite number when present")


@dataclass(frozen=True, slots=True)
class ArchitectureReviewRecoveryRequest:
    """Bounded Vidar recovery handoff within the approved ImpactEnvelope."""

    recovery_id: str
    review_case_id: str
    change_id: str
    action_run_id: str
    impact_envelope_id: str
    rollback_ref: str
    stop_condition_ref: str
    failed_effect_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    requested_at: datetime
    target_agent: Literal["Vidar"] = field(default="Vidar", init=False)
    arb_execution_authority: Literal[False] = field(default=False, init=False)

    def to_mapping(self) -> dict[str, object]:
        return {
            "recovery_id": self.recovery_id,
            "review_case_id": self.review_case_id,
            "change_id": self.change_id,
            "action_run_id": self.action_run_id,
            "impact_envelope_id": self.impact_envelope_id,
            "target_agent": self.target_agent,
            "rollback_ref": self.rollback_ref,
            "stop_condition_ref": self.stop_condition_ref,
            "failed_effect_ids": list(self.failed_effect_ids),
            "reason_codes": list(self.reason_codes),
            "requested_at": self.requested_at.isoformat(),
            "arb_execution_authority": self.arb_execution_authority,
        }


@dataclass(frozen=True, slots=True)
class ArchitectureReviewEffectClosureResult:
    """Deterministic multi-effect closure verdict for one ARB-linked ActionRun."""

    review_case_id: str
    change_id: str
    decision_case_id: str
    impact_envelope_id: str
    action_run_id: str
    status: Literal["closed_conformant", "pending_observation", "recovery_required"]
    review_status: Literal["conformant", "pending", "reopened"]
    closed_effect_ids: tuple[str, ...]
    pending_effect_ids: tuple[str, ...]
    failed_effect_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    recovery_request: ArchitectureReviewRecoveryRequest | None
    closure_digest: str
    arb_execution_authority: Literal[False] = field(default=False, init=False)

    def to_mapping(self) -> dict[str, object]:
        return {
            "review_case_id": self.review_case_id,
            "change_id": self.change_id,
            "decision_case_id": self.decision_case_id,
            "impact_envelope_id": self.impact_envelope_id,
            "action_run_id": self.action_run_id,
            "status": self.status,
            "review_status": self.review_status,
            "closed_effect_ids": list(self.closed_effect_ids),
            "pending_effect_ids": list(self.pending_effect_ids),
            "failed_effect_ids": list(self.failed_effect_ids),
            "reason_codes": list(self.reason_codes),
            "recovery_request": (
                self.recovery_request.to_mapping() if self.recovery_request is not None else None
            ),
            "closure_digest": self.closure_digest,
            "arb_execution_authority": self.arb_execution_authority,
        }


def evaluate_architecture_review_effect_closure(
    link: ArchitectureReviewActionRunLink,
    observations: Sequence[ArchitectureReviewEffectObservation],
    *,
    allowed_observer_principals: frozenset[str] = frozenset({"Heimdall"}),
) -> ArchitectureReviewEffectClosureResult:
    """Evaluate multi-effect closure without allowing self-scored or incomplete success."""

    if not allowed_observer_principals:
        raise ValueError("allowed_observer_principals MUST NOT be empty")
    if link.executor_principal in allowed_observer_principals:
        raise ValueError("executor_principal MUST NOT be an allowed independent observer")

    expected_by_id = {effect.effect_id: effect for effect in link.expected_effects}
    accepted_by_effect: dict[str, list[ArchitectureReviewEffectObservation]] = {}
    reasons: set[str] = set()

    for obs in observations:
        if obs.action_run_id != link.action_run_id:
            reasons.add(f"action_run_mismatch:{obs.observation_id}")
            continue
        if obs.effect_id not in expected_by_id:
            reasons.add(f"unknown_effect:{obs.effect_id}")
            continue
        if (
            obs.observer_principal == link.executor_principal
            or obs.observer_principal not in allowed_observer_principals
        ):
            reasons.add(f"self_scored_or_unauthorized_observer:{obs.observer_principal}")
            continue
        effect_spec = expected_by_id[obs.effect_id]
        window_end = link.executed_at + timedelta(seconds=effect_spec.window_seconds)
        if obs.observed_at < link.executed_at or obs.observed_at > window_end:
            reasons.add(f"observation_outside_window:{obs.effect_id}")
            continue
        accepted_by_effect.setdefault(obs.effect_id, []).append(obs)

    closed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    latest_failure_time: datetime | None = None

    for effect in link.expected_effects:
        candidates = accepted_by_effect.get(effect.effect_id, [])
        if not candidates:
            pending.append(effect.effect_id)
            reasons.add(f"missing_observation:{effect.effect_id}")
            continue
        ordered = sorted(
            candidates,
            key=lambda item: (item.observed_at, item.observation_id, item.evidence_digest),
        )
        effect_failed = False
        effect_complete = True
        for item in ordered:
            if item.stop_condition_triggered:
                effect_failed = True
                reasons.add(f"stop_condition_triggered:{effect.effect_id}")
            if item.protected_objective_violated:
                effect_failed = True
                reasons.add(f"protected_objective_violated:{effect.effect_id}")
            if not item.complete or item.observed_value is None:
                effect_complete = False
                reasons.add(f"incomplete_observation:{effect.effect_id}")
            elif not (effect.expected_min <= item.observed_value <= effect.expected_max):
                effect_failed = True
                reasons.add(f"effect_out_of_bounds:{effect.effect_id}")
            if effect_failed and (
                latest_failure_time is None or item.observed_at > latest_failure_time
            ):
                latest_failure_time = item.observed_at

        if effect_failed:
            failed.append(effect.effect_id)
        elif not effect_complete:
            pending.append(effect.effect_id)
        else:
            closed.append(effect.effect_id)

    sorted_reasons = tuple(sorted(reasons))
    recovery_request: ArchitectureReviewRecoveryRequest | None = None
    if failed:
        status: Literal["closed_conformant", "pending_observation", "recovery_required"] = (
            "recovery_required"
        )
        review_status: Literal["conformant", "pending", "reopened"] = "reopened"
        if latest_failure_time is None:
            raise RuntimeError("failed effect observation is missing timestamp")
        recovery_request = ArchitectureReviewRecoveryRequest(
            recovery_id=f"arb-recovery:{link.action_run_id}",
            review_case_id=link.review_case_id,
            change_id=link.change_id,
            action_run_id=link.action_run_id,
            impact_envelope_id=link.impact_envelope_id,
            rollback_ref=link.rollback_ref,
            stop_condition_ref=link.stop_condition_ref,
            failed_effect_ids=tuple(failed),
            reason_codes=sorted_reasons,
            requested_at=latest_failure_time,
        )
    elif pending or sorted_reasons:
        status = "pending_observation"
        review_status = "pending"
    else:
        status = "closed_conformant"
        review_status = "conformant"

    material = {
        "review_case_id": link.review_case_id,
        "change_id": link.change_id,
        "decision_case_id": link.decision_case_id,
        "impact_envelope_id": link.impact_envelope_id,
        "action_run_id": link.action_run_id,
        "status": status,
        "review_status": review_status,
        "closed_effect_ids": closed,
        "pending_effect_ids": pending,
        "failed_effect_ids": failed,
        "reason_codes": list(sorted_reasons),
        "recovery_request": (
            recovery_request.to_mapping() if recovery_request is not None else None
        ),
        "arb_execution_authority": False,
    }
    return ArchitectureReviewEffectClosureResult(
        review_case_id=link.review_case_id,
        change_id=link.change_id,
        decision_case_id=link.decision_case_id,
        impact_envelope_id=link.impact_envelope_id,
        action_run_id=link.action_run_id,
        status=status,
        review_status=review_status,
        closed_effect_ids=tuple(closed),
        pending_effect_ids=tuple(pending),
        failed_effect_ids=tuple(failed),
        reason_codes=sorted_reasons,
        recovery_request=recovery_request,
        closure_digest=_digest(material),
    )


__all__ = [
    "ArchitectureReviewActionRunLink",
    "ArchitectureReviewEffectClosureResult",
    "ArchitectureReviewEffectObservation",
    "ArchitectureReviewExpectedEffect",
    "ArchitectureReviewRecoveryRequest",
    "evaluate_architecture_review_effect_closure",
]
