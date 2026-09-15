"""Unexecuted no-network authority mechanics with actual Var and persisted-registry readers.

All positive receipts, role observations and promotion verification below are explicit unit
fixtures, not approvals, production verification or evidence of operational promotion.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fdai.core.detection.alert_noise.execution import (
    ALERT_ACTIONS,
    RESTORE_ACTION,
    AlertExecutionHeld,
    AlertRecoveryAdmission,
    alert_execution_key,
    alert_publication_digest,
)
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.executor.safeguards import full_action_digest
from fdai.core.workflow.workflow_runtime import workflow_approval_state_key
from fdai.delivery.alert_noise_authority import (
    ALERT_AUTHORITY_PURPOSE,
    ALERT_DISPATCH_PURPOSE,
    ALERT_RECOVERY_PURPOSE,
    StateStoreAlertAuthorityReader,
    StateStoreAlertRecoveryAuthorityReader,
    alert_dispatch_binding,
)
from fdai.delivery.alert_noise_evidence import ALERT_SCOPE_EVIDENCE_PURPOSE
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.shared.contracts.models import (
    Mode,
    OntologyDeclarationKind,
    OntologyTypeRef,
    Operation,
    RollbackKind,
    RollbackRef,
    WorkflowActionRef,
)
from fdai.shared.providers.remediation_pr import RemediationPr
from fdai_service_contracts.alert_noise import NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertDispatchEvidence,
    AlertTreatment,
)

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.executor.test_executor import _action
from tests.delivery.test_alert_noise_evidence import (
    SCOPE_KEY,
    SOURCE,
    _base_and_enrichment,
    _install_record,
)
from tests.delivery.test_alert_noise_evidence import ledger as ledger

IDENTITIES = {
    f"00000000-0000-0000-0000-{index:012d}": f"principal:{index:064x}" for index in range(1, 5)
}
REQUESTER, EXECUTOR, SERVICE_OWNER, CHANGE_OWNER = tuple(IDENTITIES.values())


class _ExactPromotionFixture:
    """Test-only verifier accepting only an explicitly installed full O7 attribution tuple."""

    def __init__(self) -> None:
        self.expected = {}
        self.calls = []

    async def verify(self, **values):
        self.calls.append(values)
        return self.expected.get(values.get("action_type")) == values


async def _promotion_fixture(h, action_type):
    values = dict(
        action_type=action_type,
        action_type_version="1.0.0",
        action_type_digest="b" * 64,
        evidence_digest="c" * 64,
        fdai_revision=SOURCE[7:],
        scenario_set_version="fixture-alert-v1",
    )
    h.verifier.expected[action_type] = values
    await h.store.write_state(
        "action_promotion:" + action_type,
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "action_type": action_type,
            "mode": "enforce",
            "promoted_at": h.clock[0].isoformat(),
            "demoted_at": None,
            "metrics": None,
            "promotion_evidence_digest": values["evidence_digest"],
            "fdai_revision": values["fdai_revision"],
            "scenario_set_version": values["scenario_set_version"],
            "action_type_version": "1.0.0",
            "action_type_digest": values["action_type_digest"],
        },
    )


async def _var_fixture(h, decisions, *, step="approve_plan", attempt=1):
    """Use the real Var request/slot structure, then install isolated simulated human decisions."""
    var = StateStoreWorkflowApprovalProvider(store=h.store)
    await var.ensure_requested(
        process_id="process:alert",
        step_id=step,
        correlation_id="correlation:alert",
        target_resource_id=h.plan.treatment.processing_rule_ref or h.plan.treatment.target_ref,
        requester_principal=next(oid for oid, ref in h.identities.items() if ref == REQUESTER),
        required_role="Owner",
        quorum=2,
        no_self_approval=True,
        timeout_seconds=43200,
        requested_at=h.clock[0],
        attempt=attempt,
    )
    key = workflow_approval_state_key("process:alert", step, attempt)
    raw = await h.store.read_state(key)
    raw["decision_claims"] = {
        slot["idempotency_key"]: {
            "principal": next(
                oid for oid, ref in h.identities.items() if ref == decision.principal_ref
            ),
            "decision": decision.decision,
            "receipt_ref": decision.receipt_ref,
        }
        for slot, decision in zip(raw["slots"], decisions, strict=True)
    }
    raw.update(state="approved", revision=2)
    await h.store.write_state(key, raw)
    return key


def _pr_fixture(action, plan, *, restore=False):
    before, after = '{"example":"before"}\n', '{"example":"after"}\n'
    if restore:
        before, after = after, before
    return RemediationPr(
        action_id=action.action_id,
        idempotency_key=action.idempotency_key,
        rule_ids=tuple(action.citing_rules),
        title="Fixture manual review",
        body="No operational effect claimed.",
        patch=after,
        patch_path="infra/example.tf.json",
        labels=("enforce", "hil", "require-manual-merge"),
        mode=Mode.ENFORCE,
        metadata={
            "action_type": action.action_type,
            "plan_digest": digest_record(plan),
            "executor_identity_ref": EXECUTOR,
            "source_digest": "sha256:" + hashlib.sha256(before.encode()).hexdigest(),
            "result_digest": "sha256:" + hashlib.sha256(after.encode()).hexdigest(),
        },
    )


@pytest.fixture
async def authority_case(ledger, evidence):
    h = ledger
    h.base, h.evidence = _base_and_enrichment(evidence)
    h.policy = NoisePolicy()
    treatment = AlertTreatment(
        kind="routing",
        target_ref="rule:example",
        remove_group_ref="group:old",
        replacement_group_ref="group:new",
    )
    h.plan = plan_alert_change(
        h.evidence, treatment, policy=h.policy, requester_ref=REQUESTER, now=h.clock[0]
    )
    digest = digest_record(h.plan)
    h.registry = {
        name: OntologyTypeRef(
            kind=OntologyDeclarationKind.ACTION,
            name=name,
            version="1.0.0",
            catalog_digest="sha256:" + "b" * 64,
        )
        for name in ALERT_ACTIONS
    }
    h.action = _action(
        mode=Mode.ENFORCE,
        target="rule:example",
        params={"plan_digest": digest[7:]},
        idempotency_key=alert_execution_key(h.plan.action_type, digest),
    ).model_copy(
        update={
            "action_type": h.plan.action_type,
            "action_type_ref": h.registry[h.plan.action_type],
            "operation": Operation.UPDATE,
            "created_at": h.clock[0],
            "executor_identity_ref": EXECUTOR,
            "rollback_ref": RollbackRef(kind=RollbackKind.PR_REVERT, reference=h.plan.rollback_ref),
            "workflow_action": WorkflowActionRef(
                process_id="process:alert", step_id="update_routing", proposal_ref="proposal:alert"
            ),
        }
    )
    h.pr = _pr_fixture(h.action, h.plan)
    h.dispatch = AlertDispatchEvidence(
        plan_digest=digest,
        evidence_digest=h.plan.evidence_digest,
        policy_digest=h.plan.policy_digest,
        target_revision=h.plan.target_revision,
        evaluated_at=h.clock[0],
        valid_until=h.clock[0] + timedelta(minutes=5),
        authorization_until=h.clock[0] + timedelta(hours=12),
        executor_ref=EXECUTOR,
        dry_run_digest=alert_publication_digest(h.plan, h.pr),
        promotion_digest="sha256:" + "c" * 64,
        writer_fence_ref="mechanism:fixture",
        audit_intent_ref="audit:fixture",
        recovery_admission_ref="recovery:fixture",
        dependencies_current=True,
        actors_current=True,
        observer_ready=True,
        recovery_ready=True,
        kill_switch=False,
        mode="enforce",
    )
    h.approvals = tuple(
        AlertApproval(
            plan_digest=digest,
            principal_ref=principal,
            tenant_ref=h.plan.tenant_ref,
            scope_ref=h.plan.scope_ref,
            decision="approved",
            lane=lane,
            service_refs=h.plan.service_refs,
            decided_at=h.clock[0],
            expires_at=h.clock[0] + timedelta(hours=12),
            receipt_ref="approval:" + lane,
            authority_revision="sha256:" + "d" * 64,
        )
        for principal, lane in ((SERVICE_OWNER, "service_owner"), (CHANGE_OWNER, "change_owner"))
    )
    h.identities, h.verifier = dict(IDENTITIES), _ExactPromotionFixture()
    h.promotions = StateStoreActionPromotionRegistry(
        store=h.store, persisted_authority_verifier=h.verifier
    )
    await _promotion_fixture(h, h.plan.action_type)
    h.var_key = await _var_fixture(h, h.approvals)
    h.authority_key = "alert-noise:authority:" + digest
    h.payload = dict(
        plan_digest=digest,
        approvals=[item.model_dump(mode="json") for item in h.approvals],
        dispatch=h.dispatch.model_dump(mode="json"),
        process_id="process:alert",
        approval_step_id="approve_plan",
        attempt=1,
    )
    await _install_record(
        h, key=h.authority_key, payload=h.payload, purpose=ALERT_AUTHORITY_PURPOSE
    )
    h.source_receipt, _ = await _install_record(
        h,
        key=SCOPE_KEY,
        purpose=ALERT_SCOPE_EVIDENCE_PURPOSE,
        payload={
            "base_digest": digest_record(h.base),
            "evidence": h.evidence.model_dump(mode="json"),
        },
    )
    h.options = dict(
        store=h.store,
        admissions=h.admissions,
        promotion_registry=h.promotions,
        principal_refs=h.identities,
        scope_ref=h.plan.scope_ref,
        tenant_ref=h.plan.tenant_ref,
        source_revision=SOURCE,
        clock=lambda: h.clock[0],
    )
    h.reader, h.recovery_reader = (
        StateStoreAlertAuthorityReader(**h.options),
        StateStoreAlertRecoveryAuthorityReader(**h.options),
    )
    return h


async def _recovery_fixture(h, *, action_step=None):
    h.clock[0] += timedelta(days=2)
    step = "recover_" + "d" * 32
    action = h.action.model_copy(
        update={
            "action_id": UUID(int=20),
            "action_type": RESTORE_ACTION,
            "action_type_ref": h.registry[RESTORE_ACTION],
            "created_at": h.clock[0],
            "idempotency_key": alert_execution_key(RESTORE_ACTION, digest_record(h.plan)),
            "workflow_action": WorkflowActionRef(
                process_id="process:alert",
                step_id=action_step or step,
                proposal_ref="proposal:recover",
            ),
        }
    )
    pr = _pr_fixture(action, h.plan, restore=True)
    approvals = tuple(
        item.model_copy(
            update={
                "decided_at": h.clock[0],
                "expires_at": h.clock[0] + timedelta(hours=12),
                "receipt_ref": "recovery-approval:" + item.lane,
            }
        )
        for item in h.approvals
    )
    var_key = await _var_fixture(h, approvals, step=step)
    await _promotion_fixture(h, RESTORE_ACTION)
    receipt = AlertRecoveryAdmission(
        action_digest=full_action_digest(action),
        plan_digest=digest_record(h.plan),
        rollback_ref=h.plan.rollback_ref,
        dry_run_digest=alert_publication_digest(h.plan, pr),
        executor_ref=EXECUTOR,
        receipt_ref="recovery:current",
        evaluated_at=h.clock[0],
        valid_until=h.clock[0] + timedelta(minutes=5),
        authorization_until=h.clock[0] + timedelta(hours=1),
    )
    payload = dict(
        plan_digest=digest_record(h.plan),
        admission=receipt.model_dump(mode="json"),
        approvals=[item.model_dump(mode="json") for item in approvals],
        promotion_digest="sha256:" + "c" * 64,
        process_id="process:alert",
        approval_step_id=step,
        attempt=1,
    )
    key = "alert-noise:recovery-authority:" + full_action_digest(action)
    await _install_record(h, key=key, payload=payload, purpose=ALERT_RECOVERY_PURPOSE)
    return SimpleNamespace(
        action=action,
        pr=pr,
        approvals=approvals,
        receipt=receipt,
        key=key,
        payload=payload,
        var_key=var_key,
    )


async def test_actual_var_and_verified_registry_supply_only_pseudonymous_authority(authority_case):
    h = authority_case
    assert await h.reader.approvals(h.plan) == h.approvals
    assert await h.reader.dispatch_evidence(h.plan) == h.dispatch
    assert h.verifier.calls and {item["action_type"] for item in h.verifier.calls} == {
        h.plan.action_type
    }
    resolved = await h.reader.read(h.plan)
    assert all(oid not in repr(resolved) for oid in IDENTITIES)
    assert resolved.proof.admission.execution_authority is False


async def test_no_admission_or_missing_record_is_held_not_default_permissions(authority_case):
    h = authority_case
    reader = StateStoreAlertAuthorityReader(**{**h.options, "admissions": None})
    assert await reader.approvals(h.plan) == ()
    with pytest.raises(AlertExecutionHeld, match="missing"):
        await reader.dispatch_evidence(h.plan)
    assert (
        await h.reader.approvals(h.plan.model_copy(update={"requester_ref": SERVICE_OWNER})) == ()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("no_self_approval", False),
        ("quorum", 1),
        ("quorum", True),
        ("required_role", "Contributor"),
        ("state", "cancelled"),
        ("state", "rejected"),
        ("state", "timed_out"),
        ("target_resource_id", "rule:other"),
        ("attempt", True),
        ("revision", "2"),
    ],
)
async def test_admitted_payload_cannot_override_actual_var_policy(authority_case, field, value):
    h = authority_case
    raw = await h.store.read_state(h.var_key)
    raw[field] = value
    await h.store.write_state(h.var_key, raw)
    with pytest.raises(AlertExecutionHeld):
        await h.reader.dispatch_evidence(h.plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal", next(iter(IDENTITIES))),
        ("decision", "rejected"),
        ("receipt_ref", "approval:other"),
    ],
)
async def test_actual_decision_principal_and_receipt_must_match(authority_case, field, value):
    h = authority_case
    raw = await h.store.read_state(h.var_key)
    next(iter(raw["decision_claims"].values()))[field] = value
    await h.store.write_state(h.var_key, raw)
    with pytest.raises(AlertExecutionHeld):
        await h.reader.approvals(h.plan)


@pytest.mark.parametrize("change", ["removed", "alias", "raw", "duplicate", "case"])
async def test_private_mapping_is_exact_scoped_and_revocable(authority_case, change):
    h = authority_case
    oid = next(iter(h.identities))
    if change == "removed":
        del h.identities[oid]
    elif change == "alias":
        h.identities[oid + " "] = h.identities.pop(oid)
    elif change == "raw":
        h.identities[oid] = oid
    elif change == "case":
        h.identities[oid] = h.identities[oid].upper()
    else:
        h.identities[oid] = EXECUTOR
    with pytest.raises(AlertExecutionHeld) as failure:
        await h.reader.dispatch_evidence(h.plan)
    assert all(private not in str(failure.value) for private in IDENTITIES)


@pytest.mark.parametrize("change", ["shadow", "wrong-evidence", "missing-verifier"])
async def test_registry_is_refreshed_not_inferred_from_dispatch_flags(authority_case, change):
    h = authority_case
    await h.reader.read(h.plan)
    if change == "missing-verifier":
        h.verifier.expected.clear()
    else:
        raw = await h.store.read_state("action_promotion:" + h.plan.action_type)
        raw["mode" if change == "shadow" else "promotion_evidence_digest"] = (
            "shadow" if change == "shadow" else "f" * 64
        )
        await h.store.write_state("action_promotion:" + h.plan.action_type, raw)
    with pytest.raises(AlertExecutionHeld):
        await h.reader.dispatch_evidence(h.plan)
    assert h.promotions.mode_of(h.plan.action_type) is Mode.SHADOW


async def test_full_action_dispatch_proof_is_separate_from_approval(authority_case):
    h = authority_case
    authority = await h.reader.read(h.plan)
    args = dict(
        action=h.action,
        plan=h.plan,
        pr=h.pr,
        authority=authority,
        evidence_receipt_digest=h.source_receipt.receipt_digest,
        evaluation_admission_digest=None,
    )
    assert await h.reader.dispatch_proof(**args) is None
    await _install_record(
        h,
        key="alert-noise:dispatch:" + full_action_digest(h.action),
        purpose=ALERT_DISPATCH_PURPOSE,
        payload=alert_dispatch_binding(**args),
    )
    assert await h.reader.dispatch_proof(**args) is not None
    with pytest.raises(AlertExecutionHeld, match="mismatch"):
        await h.reader.dispatch_proof(**{**args, "pr": replace(h.pr, patch=h.pr.patch + " ")})


async def test_dispatch_statement_false_is_not_numeric_zero(authority_case):
    h = authority_case
    authority = await h.reader.read(h.plan)
    args = dict(
        action=h.action,
        plan=h.plan,
        pr=h.pr,
        authority=authority,
        evidence_receipt_digest=h.source_receipt.receipt_digest,
        evaluation_admission_digest=None,
    )
    payload = {**alert_dispatch_binding(**args), "execution_authority": 0}
    await _install_record(
        h,
        key="alert-noise:dispatch:" + full_action_digest(h.action),
        purpose=ALERT_DISPATCH_PURPOSE,
        payload=payload,
    )
    with pytest.raises(AlertExecutionHeld, match="mismatch"):
        await h.reader.dispatch_proof(**args)


@pytest.mark.parametrize("subject", ["approval", "dispatch"])
async def test_decisions_cannot_postdate_the_receipt_that_claims_to_verify_them(
    authority_case, subject
):
    h = authority_case
    later = (h.clock[0] + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    if subject == "approval":
        h.payload["approvals"][0]["decided_at"] = later
    else:
        h.payload["dispatch"]["evaluated_at"] = later
    await _install_record(
        h, key=h.authority_key, payload=h.payload, purpose=ALERT_AUTHORITY_PURPOSE
    )
    h.clock[0] += timedelta(minutes=2)
    with pytest.raises(AlertExecutionHeld):
        await h.reader.dispatch_evidence(h.plan)


async def test_recovery_reads_a_separate_current_var_attempt_after_forward_expiry(authority_case):
    h = authority_case
    recovery = await _recovery_fixture(h)
    assert h.clock[0] > h.plan.expires_at
    assert (
        await h.recovery_reader.admission(action=recovery.action, plan=h.plan) == recovery.receipt
    )
    assert h.verifier.calls[-1]["action_type"] == RESTORE_ACTION
    assert await h.recovery_reader.admission(action=h.action, plan=h.plan) is None


async def test_compensation_action_retains_its_separate_var_recovery_approval_step(authority_case):
    h = authority_case
    recovery = await _recovery_fixture(h, action_step="compensate_update_routing")
    assert recovery.payload["approval_step_id"] != recovery.action.workflow_action.step_id
    assert (
        await h.recovery_reader.admission(action=recovery.action, plan=h.plan) == recovery.receipt
    )


@pytest.mark.parametrize(
    "change", ["purpose", "forward-receipt", "action", "step", "attempt", "rollback", "executor"]
)
async def test_recovery_never_reuses_or_rebinds_forward_approval(authority_case, change):
    h = authority_case
    recovery = await _recovery_fixture(h)
    payload = recovery.payload
    purpose = ALERT_RECOVERY_PURPOSE
    if change == "purpose":
        purpose = ALERT_AUTHORITY_PURPOSE
    elif change == "forward-receipt":
        payload["approvals"][0]["receipt_ref"] = h.approvals[0].receipt_ref
    elif change == "step":
        payload["approval_step_id"] = "approve_plan"
    elif change == "attempt":
        payload["attempt"] = 2
    else:
        field = {"action": "action_digest", "rollback": "rollback_ref", "executor": "executor_ref"}[
            change
        ]
        payload["admission"][field] = (
            SERVICE_OWNER if change == "executor" else "sha256:" + "f" * 64
        )
    await _install_record(h, key=recovery.key, payload=payload, purpose=purpose)
    with pytest.raises(AlertExecutionHeld):
        await h.recovery_reader.admission(action=recovery.action, plan=h.plan)
