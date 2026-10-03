"""Forseti-owned wire safeguard builders for executable verdicts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.topics import stable_idempotency_key

#: The triggering event carried an upstream what-if or dry-run receipt.
DRY_RUN_UPSTREAM_RECEIPT = "upstream_receipt"
#: No upstream receipt exists; the value is a deterministic obligation identity, not proof
#: that a dry-run ran. Proving it before executor I/O is the planned Thor pre-flight simulation.
DRY_RUN_DECLARED_OBLIGATION = "declared_obligation"


def execution_safeguards(
    *,
    action_type: str,
    action_idempotency_key: str,
    resource_id: object,
    rollback_contract: str,
    event: Mapping[str, Any],
) -> dict[str, object]:
    upstream_receipt = str(event.get("dry_run_receipt") or event.get("what_if_receipt") or "")
    dry_run_receipt = upstream_receipt.strip() or stable_idempotency_key(
        "forseti-dry-run-obligation", action_idempotency_key, action_type
    )
    return {
        "dry_run_evidence": (
            DRY_RUN_UPSTREAM_RECEIPT if upstream_receipt.strip() else DRY_RUN_DECLARED_OBLIGATION
        ),
        "stop_condition": str(event.get("stop_condition") or f"{action_type}:effect_verified"),
        "tested_rollback_contract": str(
            event.get("tested_rollback_contract") or f"{rollback_contract}:declared"
        ),
        "blast_radius_limit": event.get("blast_radius_limit")
        or {"scope": "resource", "resource_id": str(resource_id or "")},
        "dry_run_receipt": dry_run_receipt,
        "logical_target_lock": str(event.get("logical_target_lock") or resource_id or ""),
        "stable_idempotency_key": action_idempotency_key,
        "two_phase_audit_intent": str(
            event.get("two_phase_audit_intent")
            or stable_idempotency_key("forseti-audit-intent", action_idempotency_key, action_type)
        ),
    }


def arbitration_safeguards(
    *,
    action_type: str,
    action_idempotency_key: str,
    resource_id: object,
    rollback_contract: str,
) -> dict[str, object]:
    return {
        "dry_run_evidence": DRY_RUN_DECLARED_OBLIGATION,
        "stop_condition": f"{action_type}:effect_verified",
        "tested_rollback_contract": f"{rollback_contract}:declared",
        "blast_radius_limit": {"scope": "resource", "resource_id": str(resource_id or "")},
        "dry_run_receipt": stable_idempotency_key(
            "forseti-arbitration-dry-run-obligation", action_idempotency_key, action_type
        ),
        "logical_target_lock": str(resource_id or ""),
        "stable_idempotency_key": action_idempotency_key,
        "two_phase_audit_intent": stable_idempotency_key(
            "forseti-arbitration-audit-intent", action_idempotency_key, action_type
        ),
    }


def attach_arbitration_safeguards(
    verdict: dict[str, Any],
    risk_verdict: str,
    action_type: str,
    action_idempotency_key: str,
    resource_id: object,
    rollback_contract: str,
) -> None:
    if risk_verdict in {"auto", "hil"}:
        verdict["safeguards"] = arbitration_safeguards(
            action_type=action_type,
            action_idempotency_key=action_idempotency_key,
            resource_id=resource_id,
            rollback_contract=rollback_contract,
        )


__all__ = [
    "DRY_RUN_DECLARED_OBLIGATION",
    "DRY_RUN_UPSTREAM_RECEIPT",
    "arbitration_safeguards",
    "attach_arbitration_safeguards",
    "execution_safeguards",
]
