"""Deterministic, authority-free state transitions for Norns learners."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.agents._framework.action_semantics import outcome_result
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.core.operational_learning import (
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    ShadowDwellLedger,
    ShadowDwellObservation,
)

_ADVERSE_RESULTS = frozenset({"rollback", "failure", "reverted"})
_SUCCESS_RESULTS = frozenset({"success", "applied", "ok"})
_SHADOW_INSTANT_KEYS = ("observed_at", "occurred_at", "recorded_at", "timestamp")


class NornsLearningState(Protocol):
    """Minimum Norns-owned state required by deterministic learners."""

    _approval_counts: dict[str, dict[str, int]]
    _approval_proposed: set[str]
    _counted_approvals: BoundedLruSet[str]
    _counted_correlations: BoundedLruSet[str]
    _counted_shadow_outcomes: BoundedLruSet[str]
    _fingerprint_counter: BoundedLruDict[str, int]
    _min_outcome_samples: int
    _outcome_proposed: set[str]
    _outcomes: dict[str, dict[str, int]]
    _override_counter: Counter[str]
    _override_proposed: set[str]
    _override_retire_threshold: int
    _promotion_threshold: int
    _proposed: BoundedLruSet[str]
    _rejection_revise_threshold: int
    _rollback_alarm_rate: float
    _shadow_dwell: ShadowDwellLedger

    def _append_candidate(self, candidate: dict[str, Any]) -> None: ...

    def _ensure_pending_capacity(self) -> None: ...

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


def observe_fingerprint(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose one inert candidate after a fingerprint repeats enough times."""
    fingerprint = str(payload.get("fingerprint", ""))
    if not fingerprint:
        return
    count = (state._fingerprint_counter.get(fingerprint) or 0) + 1
    state._fingerprint_counter.set(fingerprint, count)
    if count < state._promotion_threshold or fingerprint in state._proposed:
        return
    state._proposed.add(fingerprint)
    state._append_candidate(
        {
            "source_signal": "handoff_fingerprint",
            "evidence": {"fingerprint": fingerprint, "occurrence_count": count},
            "proposed_by": "Norns",
            "proposal_kind": "new",
        }
    )


def observe_outcome(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose a safer threshold after measured rollback evidence clears its floor."""
    target = str(payload.get("action_type") or payload.get("rule_id") or "")
    if payload.get("shadow_mode"):
        retain_shadow_dwell(state, target, payload)
        return
    result = str(payload.get("result", "")).lower()
    if not result:
        result = outcome_result(str(payload.get("state", ""))) or ""
    if not target:
        return
    if result in _ADVERSE_RESULTS:
        bucket = "rollback"
    elif result in _SUCCESS_RESULTS:
        bucket = "success"
    else:
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if correlation_id:
        outcome_key = f"{correlation_id}:{target}"
        if outcome_key in state._counted_correlations:
            return
        state._counted_correlations.add(outcome_key)
    counts = state._outcomes.setdefault(target, {"success": 0, "rollback": 0})
    counts[bucket] += 1
    total = counts["success"] + counts["rollback"]
    if total < state._min_outcome_samples or target in state._outcome_proposed:
        return
    rollback_rate = counts["rollback"] / total
    if rollback_rate <= state._rollback_alarm_rate:
        return
    state._outcome_proposed.add(target)
    state._append_candidate(
        {
            "source_signal": "audit_outcome",
            "evidence": {
                "target": target,
                "sample_size": total,
                "rollback_rate": round(rollback_rate, 4),
                "alarm_rate": state._rollback_alarm_rate,
            },
            "proposed_by": "Norns",
            "proposal_kind": "threshold_adjustment",
            "suggested_change": "raise_confidence_threshold",
            "target_rule_id": target,
        }
    )


def retain_shadow_dwell(
    state: NornsLearningState,
    target: str,
    payload: Mapping[str, Any],
) -> None:
    """Retain one valid, deduplicated judge-and-log-only observation."""
    if not target:
        return
    instant = _shadow_observed_at(payload)
    if instant is None:
        state.record_behavior("shadow_dwell_observation_untimed")
        return
    reviewed = payload.get("operator_reviewed", False)
    agreed = payload.get("operator_agreed", False)
    escape = payload.get("policy_escape", False)
    if not all(isinstance(flag, bool) for flag in (reviewed, agreed, escape)):
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if correlation_id:
        dwell_key = f"shadow:{correlation_id}:{target}"
        if dwell_key in state._counted_shadow_outcomes:
            return
        state._counted_shadow_outcomes.add(dwell_key)
    try:
        observation = ShadowDwellObservation(
            target=target,
            observed_at=instant,
            reviewed=reviewed,
            agreed=agreed and reviewed,
            policy_escape=escape,
        )
    except ShadowDwellEvidenceError:
        state.record_behavior("shadow_dwell_observation_invalid")
        return
    state._shadow_dwell.record(observation)
    state.record_behavior("shadow_dwell_observation_retained")


def shadow_dwell_evidence(
    state: NornsLearningState,
    target: str,
) -> ShadowDwellEvidence | None:
    """Return retained dwell evidence without changing candidate authority."""
    return state._shadow_dwell.evidence_for(target)


def observe_approval(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose an inert revision after recurring human rejections."""
    action_type = str(payload.get("action_type") or "")
    decision = str(payload.get("state", "")).strip().lower()
    if not action_type or decision not in ("approved", "rejected"):
        return
    correlation_id = str(payload.get("correlation_id", ""))
    if correlation_id:
        if correlation_id in state._counted_approvals:
            return
        state._counted_approvals.add(correlation_id)
    counts = state._approval_counts.setdefault(action_type, {"approved": 0, "rejected": 0})
    counts[decision] += 1
    if decision != "rejected" or action_type in state._approval_proposed:
        return
    if counts["rejected"] < state._rejection_revise_threshold:
        return
    state._approval_proposed.add(action_type)
    state._append_candidate(
        {
            "source_signal": "recurring_hil_rejection",
            "evidence": {
                "action_type": action_type,
                "rejection_count": counts["rejected"],
                "sample_size": counts["approved"] + counts["rejected"],
            },
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "target_rule_id": action_type,
        }
    )


def observe_override(state: NornsLearningState, payload: Mapping[str, Any]) -> None:
    """Propose an inert revision or retirement after recurring overrides."""
    state._ensure_pending_capacity()
    rule_id = str(payload.get("rule_id") or payload.get("target_rule_id") or "")
    event = str(payload.get("event", "create")).lower()
    if not rule_id or event not in ("create", "modify"):
        return
    state._override_counter[rule_id] += 1
    if (
        state._override_counter[rule_id] < state._override_retire_threshold
        or rule_id in state._override_proposed
    ):
        return
    state._override_proposed.add(rule_id)
    mode = str(payload.get("mode", ""))
    kind = "retirement" if mode == "disabled" else "revision"
    state._append_candidate(
        {
            "source_signal": "recurring_override",
            "evidence": {
                "rule_id": rule_id,
                "override_count": state._override_counter[rule_id],
                "latest_mode": mode,
            },
            "proposed_by": "Norns",
            "proposal_kind": kind,
            "target_rule_id": rule_id,
        }
    )


def _shadow_observed_at(payload: Mapping[str, Any]) -> datetime | None:
    for key in _SHADOW_INSTANT_KEYS:
        value = payload.get(key)
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else None
        if isinstance(value, str) and len(value) <= 64:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                return parsed
    return None


__all__ = [
    "NornsLearningState",
    "observe_approval",
    "observe_fingerprint",
    "observe_outcome",
    "observe_override",
    "retain_shadow_dwell",
    "shadow_dwell_evidence",
]
