"""Cross-check opaque approval decisions against the actual Var journal and identity map."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertApproval, AlertChangePlan
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.rbac.roles import Role
from fdai.core.workflow.workflow_runtime import workflow_approval_state_key
from fdai.delivery.alert_noise_authority_records import _ApprovalContext

if TYPE_CHECKING:
    from fdai.delivery.alert_noise_authority import _AuthorityReader


def _identity_digest(
    reader: _AuthorityReader,
    plan: AlertChangePlan,
    executor: str,
    approvals: tuple[AlertApproval, ...],
) -> str:
    """Bind only the exact current identities involved in this approval quorum."""
    refs = {plan.requester_ref, executor, *(item.principal_ref for item in approvals)}
    bindings = sorted((oid, ref) for oid, ref in reader._principal_refs.items() if ref in refs)
    if len(bindings) != len(refs) or {ref for _, ref in bindings} != refs:
        raise AlertExecutionHeld("alert_principal_mapping_changed")
    return content_digest({"scope_digest": reader._scope, "bindings": bindings})


async def _quorum(
    reader: _AuthorityReader,
    context: _ApprovalContext,
    plan: AlertChangePlan,
    executor: str,
    floor: datetime,
    end: datetime,
) -> tuple[str, datetime]:
    """Match exact scoped decisions and immutable journal reads, never normalized aliases."""
    identities = dict(reader._principal_refs)
    if not 1 <= len(identities) <= 10_000 or len(set(identities.values())) != len(identities):
        raise AlertExecutionHeld("alert_principal_mapping_invalid")
    for oid, ref in identities.items():
        if (
            type(oid) is not str
            or str(UUID(oid)) != oid
            or UUID(oid).int == 0
            or type(ref) is not str
            or re.fullmatch(r"principal:[a-f0-9]{64}", ref) is None
        ):
            raise AlertExecutionHeld("alert_principal_mapping_invalid")
    decisions = context.approvals
    principals = {item.principal_ref for item in decisions}
    receipts = {item.receipt_ref for item in decisions}
    if (
        len(principals) != len(decisions)
        or len(receipts) != len(decisions)
        or principals.intersection({plan.requester_ref, executor})
        or plan.requester_ref == executor
        or not (principals | {plan.requester_ref, executor}).issubset(identities.values())
        or {item.lane for item in decisions} != {"service_owner", "change_owner"}
        or {ref for item in decisions if item.lane == "service_owner" for ref in item.service_refs}
        != set(plan.service_refs)
    ):
        raise AlertExecutionHeld("alert_approval_quorum_mismatch")
    now = reader._clock()
    for item in decisions:
        if (
            item.plan_digest != digest_record(plan)
            or item.scope_ref != plan.scope_ref
            or item.tenant_ref != plan.tenant_ref
            or item.decision != "approved"
            or not floor <= item.decided_at <= now < item.expires_at
            or end > item.expires_at
            or not set(item.service_refs).issubset(plan.service_refs)
            or (item.lane == "service_owner" and not item.service_refs)
        ):
            raise AlertExecutionHeld("alert_approval_not_current")
    key = workflow_approval_state_key(context.process_id, context.approval_step_id, context.attempt)
    raw = await reader._store.read_state(key)
    if (
        raw is None
        or raw.get("process_id") != context.process_id
        or raw.get("step_id") != context.approval_step_id
        or type(raw.get("attempt")) is not int
        or raw["attempt"] != context.attempt
        or type(raw.get("revision")) is not int
        or raw["revision"] < 1
        or raw.get("required_role") != Role.OWNER.value
        or raw.get("no_self_approval") is not True
        or type(raw.get("quorum")) is not int
        or raw["quorum"] != len(decisions)
        or raw.get("state") not in {"pending", "approved"}
        or raw.get("target_resource_id")
        != (plan.treatment.processing_rule_ref or plan.treatment.target_ref)
    ):
        raise AlertExecutionHeld("alert_var_policy_mismatch")
    journal_digest = content_digest(raw)
    snapshot = await reader._var.read_snapshot(
        process_id=context.process_id, step_id=context.approval_step_id, attempt=context.attempt
    )
    if (
        snapshot is None
        or snapshot.revision != raw["revision"]
        or (snapshot.process_id, snapshot.step_id, snapshot.attempt)
        != (context.process_id, context.approval_step_id, context.attempt)
        or snapshot.timed_out
        or snapshot.cancelled
        or identities.get(snapshot.requester_principal) != plan.requester_ref
        or snapshot.expires_at is None
        or not floor <= snapshot.requested_at <= now < snapshot.expires_at
        or end > snapshot.expires_at
        or any(item.decided_at < snapshot.requested_at for item in decisions)
        or len(snapshot.decisions) != len(decisions)
        or {
            (identities.get(item.principal), item.decision, item.receipt_ref)
            for item in snapshot.decisions
        }
        != {(item.principal_ref, item.decision, item.receipt_ref) for item in decisions}
    ):
        raise AlertExecutionHeld("alert_var_decision_mismatch")
    current = await reader._store.read_state(key)
    if (
        current is None
        or content_digest(current) != journal_digest
        or identities != dict(reader._principal_refs)
    ):
        raise AlertExecutionHeld("alert_var_changed")
    return journal_digest, min(snapshot.expires_at, *(item.expires_at for item in decisions))
