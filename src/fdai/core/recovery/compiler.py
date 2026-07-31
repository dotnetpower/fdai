"""Compile version-pinned recovery plans and compensation order."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fdai.core.recovery.models import (
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryPlanStatus,
    RecoveryStrategy,
)


def reverse_topological_compensation(actions: tuple[RecoveryAction, ...]) -> tuple[str, ...]:
    by_id = {item.action_id: item for item in actions}
    if len(by_id) != len(actions):
        raise ValueError("recovery action ids MUST be unique")
    for action in actions:
        missing = set(action.depends_on) - set(by_id)
        if missing:
            raise ValueError(f"recovery action {action.action_id} has dangling dependencies")
        if not action.compensation_action_type_ref or not action.rollback_ref:
            raise ValueError(f"recovery action {action.action_id} lacks compensation evidence")
        if not action.stop_conditions:
            raise ValueError(f"recovery action {action.action_id} lacks stop conditions")

    incoming = {action_id: set(action.depends_on) for action_id, action in by_id.items()}
    ready = sorted(action_id for action_id, dependencies in incoming.items() if not dependencies)
    forward: list[str] = []
    while ready:
        action_id = ready.pop(0)
        forward.append(action_id)
        for candidate in sorted(incoming):
            if action_id not in incoming[candidate]:
                continue
            incoming[candidate].remove(action_id)
            if not incoming[candidate] and candidate not in forward and candidate not in ready:
                ready.append(candidate)
                ready.sort()
    if len(forward) != len(actions):
        raise ValueError("recovery action dependencies MUST be acyclic")
    return tuple(reversed(forward))


def compile_recovery_plan(
    *,
    strategy: RecoveryStrategy,
    workflow_ref: str,
    workflow_version: str,
    catalog_digest: str,
    actions: tuple[RecoveryAction, ...],
    impact_envelope_id: str,
    recovery_objective_ref: str,
    verification_probes: tuple[str, ...],
    direct_target_ids: tuple[str, ...],
    graph_revision: str,
    dry_run_receipt: str,
    last_rehearsed_at: datetime,
    expires_at: datetime,
) -> RecoveryPlanRecord:
    compensation_order = reverse_topological_compensation(actions)
    status = (
        RecoveryPlanStatus.READY
        if dry_run_receipt.strip() and verification_probes and last_rehearsed_at <= expires_at
        else RecoveryPlanStatus.DRAFT
    )
    identity = hashlib.sha256(
        json.dumps(
            {
                "actions": [
                    (item.action_id, item.action_type_ref, item.action_type_version)
                    for item in actions
                ],
                "catalog": catalog_digest,
                "envelope": impact_envelope_id,
                "targets": sorted(direct_target_ids),
                "workflow": (workflow_ref, workflow_version),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return RecoveryPlanRecord(
        plan_id=f"recovery-{identity[:32]}",
        strategy=strategy,
        status=status,
        workflow_ref=workflow_ref,
        workflow_version=workflow_version,
        catalog_digest=catalog_digest,
        actions=actions,
        compensation_order=compensation_order,
        impact_envelope_id=impact_envelope_id,
        recovery_objective_ref=recovery_objective_ref,
        verification_probes=tuple(dict.fromkeys(verification_probes)),
        direct_target_ids=tuple(dict.fromkeys(direct_target_ids)),
        graph_revision=graph_revision,
        dry_run_receipt=dry_run_receipt,
        last_rehearsed_at=last_rehearsed_at,
        expires_at=expires_at,
    )


__all__ = ["compile_recovery_plan", "reverse_topological_compensation"]
