"""Bounded Vidar disaster-recovery failover contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.action_run_identity import is_action_run_identity
from fdai.agents._framework.topics import stable_idempotency_key

FAILOVER_ACTION_TYPES = frozenset({"ops.failover-primary"})
DR_CONTRACT_KIND = "dr_failover_contract"
DR_OUTCOME_KIND = "dr_failover_outcome"
_MAX_TEXT = 512
_MIN_INCIDENT_QUORUM = 2


def is_failover_action_type(action_type: object) -> bool:
    return isinstance(action_type, str) and action_type in FAILOVER_ACTION_TYPES


def decision_allows_executor_io(decision: Mapping[str, Any] | None) -> bool:
    return (
        decision is not None
        and decision.get("kind") == DR_CONTRACT_KIND
        and decision.get("decision") == "accepted"
        and is_action_run_identity(decision.get("action_run_identity"))
        and isinstance(decision.get("failback_contract"), str)
        and bool(str(decision.get("failback_contract")).strip())
        and isinstance(decision.get("expected_effect_digest"), str)
        and str(decision.get("expected_effect_digest")).startswith("sha256:")
    )


def decision_hold_reason(decision: Mapping[str, Any] | None) -> str:
    if decision is None:
        return "dr_contract_missing"
    reason = decision.get("reason")
    return _bounded_text(reason) or "dr_contract_not_accepted"


def build_contract_decision(
    action_run: Mapping[str, Any],
    *,
    contract_ready: bool,
    failback_executor_bound: bool,
    now: datetime,
) -> dict[str, Any] | None:
    if not is_failover_action_type(action_run.get("action_type")):
        return None
    action_run_identity = action_run.get("action_run_identity")
    if not is_action_run_identity(action_run_identity):
        return None
    now_utc = _to_utc(now)
    trigger_kind = _trigger_kind(action_run)
    shadow_mode = bool(action_run.get("shadow_mode"))
    rollback_contract = _bounded_text(action_run.get("rollback_contract")) or "scripted"
    quorum = _positive_int(action_run.get("effective_quorum_required")) or _positive_int(
        action_run.get("quorum_required")
    )
    reason = _hold_reason(
        action_run,
        trigger_kind=trigger_kind,
        shadow_mode=shadow_mode,
        quorum=quorum,
        contract_ready=contract_ready,
        failback_executor_bound=failback_executor_bound,
    )
    decision = "held" if reason else "accepted"
    raw_params = action_run.get("params")
    params: Mapping[str, Any] = raw_params if isinstance(raw_params, Mapping) else {}
    target = _bounded_text(params.get("target_resource_ref") or action_run.get("resource_id"))
    target_region = _bounded_text(params.get("target_region"))
    request_reason = _bounded_text(params.get("reason"))
    expected_effect = {
        "target_resource_ref": target,
        "target_region": target_region,
        "trigger_kind": trigger_kind,
        "effect": "primary_failover_shadow_verified" if shadow_mode else "primary_failover",
    }
    payload: dict[str, Any] = {
        "producer_principal": "Vidar",
        "kind": DR_CONTRACT_KIND,
        "correlation_id": _bounded_text(action_run.get("correlation_id")),
        "idempotency_key": stable_idempotency_key(
            DR_CONTRACT_KIND,
            action_run_identity,
            decision,
            reason,
        ),
        "action_run_identity": action_run_identity,
        "action_type": action_run.get("action_type"),
        "resource_id": action_run.get("resource_id"),
        "decision": decision,
        "reason": reason,
        "trigger_kind": trigger_kind,
        "required_quorum": quorum,
        "failback_contract": rollback_contract,
        "failback_executor_bound": failback_executor_bound,
        "contract_ready": contract_ready,
        "expected_effect": expected_effect,
        "expected_effect_digest": _digest(expected_effect),
        "target_resource_ref": target,
        "target_region": target_region,
        "request_reason": request_reason,
        "recovery_time_budget_seconds": _positive_int(
            params.get("recovery_time_budget_seconds")
            or params.get("recovery_time_budget")
            or action_run.get("recovery_time_budget_seconds")
        ),
        "accepted_at": now_utc.isoformat() if decision == "accepted" else None,
        "decided_at": now_utc.isoformat(),
    }
    return payload


def build_outcome(
    action_run: Mapping[str, Any],
    *,
    accepted_decision: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    if not is_failover_action_type(action_run.get("action_type")):
        return None
    action_run_identity = action_run.get("action_run_identity")
    if not is_action_run_identity(action_run_identity) or not decision_allows_executor_io(
        accepted_decision
    ):
        return None
    accepted_at = _parse_datetime(accepted_decision.get("accepted_at"))
    verified_at = _parse_datetime(action_run.get("effect_verified_at")) or _to_utc(now)
    recovery_time_seconds = None
    if accepted_at is not None:
        recovery_time_seconds = max(0.0, (verified_at - accepted_at).total_seconds())
    return {
        "producer_principal": "Vidar",
        "kind": DR_OUTCOME_KIND,
        "correlation_id": _bounded_text(action_run.get("correlation_id")),
        "idempotency_key": stable_idempotency_key(DR_OUTCOME_KIND, action_run_identity),
        "action_run_identity": action_run_identity,
        "action_type": action_run.get("action_type"),
        "resource_id": action_run.get("resource_id"),
        "state": "succeeded",
        "effect_verification_ref": action_run.get("effect_verification_ref"),
        "execution_closure_ref": action_run.get("execution_closure_ref"),
        "recovery_time_seconds": recovery_time_seconds,
        "observed_at": verified_at.isoformat(),
        "expected_effect_digest": accepted_decision.get("expected_effect_digest"),
    }


def _hold_reason(
    action_run: Mapping[str, Any],
    *,
    trigger_kind: str,
    shadow_mode: bool,
    quorum: int | None,
    contract_ready: bool,
    failback_executor_bound: bool,
) -> str:
    if trigger_kind == "drill" and not shadow_mode:
        return "drill_requires_shadow"
    if not failback_executor_bound:
        return "failback_executor_unbound"
    if not contract_ready:
        return "readiness_stale"
    if not shadow_mode and action_run.get("state") != "approved":
        return "approval_required"
    if trigger_kind == "incident" and not shadow_mode and (quorum or 0) < _MIN_INCIDENT_QUORUM:
        return "quorum_below_minimum"
    return ""


def _trigger_kind(action_run: Mapping[str, Any]) -> str:
    raw = action_run.get("dr_trigger_kind")
    workflow_action = action_run.get("workflow_action")
    if raw is None and isinstance(workflow_action, Mapping):
        workflow_id = workflow_action.get("workflow_id")
        step_id = workflow_action.get("step_id")
        if workflow_id == "dr-drill-orchestration" or step_id == "dr_drill":
            raw = "drill"
    return "drill" if raw == "drill" else "incident"


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bounded_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:_MAX_TEXT]


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("Vidar DR clock MUST return a timezone-aware datetime")
    return value.astimezone(UTC)
