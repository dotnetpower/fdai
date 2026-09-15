"""No-network retained-artifact and recovery regressions; all authority proofs are unit fakes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fdai.core.detection.alert_noise.execution import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    AlertRecoveryAdmission,
    alert_execution_key,
    alert_publication_digest,
)
from fdai.core.executor.executor import ExecutorOutcome
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_iac import AlertIaCPatch
from fdai.delivery.alert_noise_pr import (
    AlertManualPrDispatcher,
    StateStoreAlertPatchReader,
    StateStoreAlertPlanReader,
)
from fdai.shared.contracts.models import Action, ExecutionPath, Mode, WorkflowActionRef
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessStatus
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertRollbackBaseline

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_execution import harness as harness
from tests.core.executor.test_safeguard_lifecycle_coordinator import (
    _AdvancingEmptyHoldReader,
    _coordinator,
)


async def test_exact_private_namespaces_and_renderer_shape(harness: SimpleNamespace) -> None:
    h = harness
    plans, patches = (
        StateStoreAlertPlanReader(store=h.store),
        StateStoreAlertPatchReader(store=h.store),
    )
    retained = await plans.read(digest_record(h.plan))
    baseline = await plans.baseline(retained)
    patch = await patches.read(retained)
    assert retained == h.plan and type(patch) is AlertIaCPatch and patch == h.patch
    assert baseline == AlertRollbackBaseline(rule=h.evidence.rules[0])
    assert digest_record(baseline) == retained.rollback_ref
    assert patch.path == "infra/example.tf.json" and patch.forward != patch.rollback
    assert not hasattr(h.delivery, "submit")


async def test_no_missing_plan_or_patch_fallback(harness: SimpleNamespace) -> None:
    h = harness
    with pytest.raises(AlertExecutionHeld, match="plan_not_retained"):
        await StateStoreAlertPlanReader(store=h.store).read("sha256:" + "f" * 64)
    other = h.plan.model_copy(update={"requester_ref": "person:other"})
    with pytest.raises(AlertExecutionHeld, match="patch_not_retained"):
        await StateStoreAlertPatchReader(store=h.store).read(other)
    assert h.publisher.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_digest", "sha256:" + "f" * 64),
        ("requester_ref", "person:other"),
        ("execution_authority", True),
        ("execution_authority", 0),
        ("extra", "not-declared"),
    ],
)
async def test_retained_plan_revalidates_full_content(harness: SimpleNamespace, field: str, value):
    h = harness
    raw = {**h.plan.model_dump(mode="json"), field: value}
    await h.store.write_state("alert-noise:plan:" + digest_record(h.plan), raw)
    with pytest.raises(ValueError):
        await StateStoreAlertPlanReader(store=h.store).read(digest_record(h.plan))


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_digest", "sha256:" + "f" * 64),
        ("forward", "changed"),
        ("rollback", "changed"),
        ("source_digest", "f" * 64),
        ("result_digest", "sha256:" + "f" * 64),
        ("forward", None),
        ("path", True),
        ("extra", "untrusted"),
    ],
)
async def test_retained_patch_rejects_unbound_or_corrupt_fields(
    harness: SimpleNamespace, field, value
):
    h = harness
    raw = {**asdict(h.patch), "plan_digest": digest_record(h.plan), field: value}
    await h.store.write_state("alert-noise:patch:" + digest_record(h.plan), raw)
    with pytest.raises(ValueError):
        await StateStoreAlertPatchReader(store=h.store).read(h.plan)


@pytest.mark.parametrize(
    "path",
    [
        "/infra/example.tf.json",
        "../example.tf.json",
        "infra/../example.tf.json",
        "./example.tf.json",
        "infra//example.tf.json",
        ".git/example.tf.json",
        "infra\\example.tf.json",
        "infra/example.tf",
        "infra/example.tf.json\n",
    ],
)
async def test_patch_paths_are_exact_not_normalized(harness: SimpleNamespace, path: str) -> None:
    h = harness
    await h.store.write_state(
        "alert-noise:patch:" + digest_record(h.plan),
        {
            **asdict(h.patch),
            "plan_digest": digest_record(h.plan),
            "path": path,
        },
    )
    with pytest.raises(AlertExecutionHeld, match="patch_path_invalid"):
        await StateStoreAlertPatchReader(store=h.store).read(h.plan)


async def test_recomputed_hash_does_not_make_a_different_patch_approved(harness: SimpleNamespace):
    h = harness
    forward = h.patch.forward.replace("unchanged", "unauthorized-change")
    digest = "sha256:" + hashlib.sha256(forward.encode()).hexdigest()
    await h.store.write_state(
        "alert-noise:patch:" + digest_record(h.plan),
        {
            **asdict(h.patch),
            "plan_digest": digest_record(h.plan),
            "forward": forward,
            "result_digest": digest,
        },
    )
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_different_existing_path_invalidates_exact_approval(harness: SimpleNamespace) -> None:
    h = harness
    await h.store.write_state(
        "alert-noise:patch:" + digest_record(h.plan),
        {
            **asdict(h.patch),
            "plan_digest": digest_record(h.plan),
            "path": "infra/other.tf.json",
        },
    )
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_digest_commits_to_source_path_bytes_and_direction(harness: SimpleNamespace) -> None:
    h = harness
    pr = await h.delivery.prepare(action=h.action, rule=h.rule, plan=h.plan)
    original = alert_publication_digest(h.plan, pr)
    changes = [
        replace(pr, patch_path="infra/other.tf.json"),
        replace(pr, patch=pr.patch + " "),
        replace(pr, metadata={**pr.metadata, "source_digest": "sha256:" + "f" * 64}),
        replace(pr, metadata={**pr.metadata, "action_type": RESTORE_ACTION}),
    ]
    assert all(alert_publication_digest(h.plan, changed) != original for changed in changes)


async def test_patch_is_re_read_at_actual_publisher_boundary(harness: SimpleNamespace) -> None:
    h = harness

    class MutatingSource:
        async def read(self, *, path: str) -> str:
            await h.store.write_state(
                "alert-noise:patch:" + digest_record(h.plan),
                {
                    **asdict(h.patch),
                    "plan_digest": digest_record(h.plan),
                    "path": "infra/other.tf.json",
                },
            )
            return h.patch.rollback

    delivery = AlertManualPrDispatcher(
        patches=StateStoreAlertPatchReader(store=h.store),
        publisher=h.publisher,
        source_reader=MutatingSource(),
    )
    result = await h.make(delivery=delivery).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert result.safeguard_bundle_digest is not None


@pytest.mark.parametrize("content", [None, "concurrent edit"])
async def test_current_iac_must_exist_at_exact_approved_revision(harness: SimpleNamespace, content):
    h = harness
    h.source.content = content
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert h.source.paths == [h.patch.path]


async def test_absent_source_reader_is_not_generic_publisher_authority(harness: SimpleNamespace):
    h = harness
    delivery = AlertManualPrDispatcher(
        patches=StateStoreAlertPatchReader(store=h.store), publisher=h.publisher
    )
    result = await h.make(delivery=delivery).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_delivery_itself_refuses_shadow(harness: SimpleNamespace) -> None:
    h = harness
    with pytest.raises(AlertExecutionHeld, match="publication_action_mismatch"):
        await h.delivery.prepare(
            action=h.action.model_copy(update={"mode": Mode.SHADOW}), rule=h.rule, plan=h.plan
        )
    assert h.publisher.calls == 0


@pytest.mark.parametrize(
    "path", [ExecutionPath.PR_NATIVE, ExecutionPath.DIRECT_API, ExecutionPath.TOOL_CALL]
)
async def test_alert_actions_have_no_direct_or_native_fallback(harness: SimpleNamespace, path):
    h = harness
    result = await h.make().execute(action=h.action, rule=h.rule, execution_path=path)
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    h.fallback.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"principal_ref": "person:requester"},
        {"principal_ref": "person:executor"},
        {"principal_ref": "person:change_owner"},
        {"service_refs": ()},
        {"decision": "rejected"},
        {"scope_ref": "scope:other"},
        {"tenant_ref": "tenant:other"},
        {"plan_digest": "sha256:" + "f" * 64},
    ],
)
async def test_all_services_and_independent_current_quorum_are_required(
    harness: SimpleNamespace, change
):
    h = harness
    first, second = h.authority.decisions
    h.authority.decisions = (first.model_copy(update=change), second)
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_freshness_interval_is_not_the_authorization_interval(
    harness: SimpleNamespace,
) -> None:
    h = harness
    h.authority.evidence = h.authority.evidence.model_copy(
        update={
            "valid_until": h.clock[0] + timedelta(seconds=30),
        }
    )
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.PUBLISHED


async def _recovery_case(h: SimpleNamespace) -> tuple[Action, SimpleNamespace]:
    """Simulate separately approved restore after forward approval and evidence have expired."""
    h.clock[0] += timedelta(days=2)
    h.source.content = h.patch.forward
    snapshot = await h.processes.get("process:alert")
    await h.processes.transition(
        process_id="process:alert",
        expected_revision=snapshot.revision,
        status=ProcessStatus.COMPENSATING,
        current_step="restore",
        event=ProcessEvent(
            event_id="event:compensating",
            process_id="process:alert",
            kind=ProcessEventKind.COMPENSATION_STARTED,
            idempotency_key="process:alert:compensating",
            recorded_at=h.clock[0],
            correlation_id="correlation:alert",
            step_id="restore",
        ),
    )
    action = h.action.model_copy(
        update={
            "action_id": UUID(int=20),
            "action_type": RESTORE_ACTION,
            "action_type_ref": h.registry[RESTORE_ACTION],
            "created_at": h.clock[0],
            "idempotency_key": alert_execution_key(RESTORE_ACTION, digest_record(h.plan)),
            "workflow_action": WorkflowActionRef(
                process_id="process:alert", step_id="restore", proposal_ref="proposal:restore"
            ),
        }
    )
    pr = await h.delivery.prepare(action=action, rule=h.rule, plan=h.plan)
    receipt = AlertRecoveryAdmission(
        action_digest=full_action_digest(action),
        plan_digest=digest_record(h.plan),
        rollback_ref=h.plan.rollback_ref,
        dry_run_digest=alert_publication_digest(h.plan, pr),
        executor_ref=action.executor_identity_ref,
        receipt_ref="recovery:separate-approval",
        evaluated_at=h.clock[0],
        valid_until=h.clock[0] + timedelta(minutes=5),
        authorization_until=h.clock[0] + timedelta(hours=1),
    )
    return action, SimpleNamespace(admission=AsyncMock(return_value=receipt))


async def test_restore_uses_separate_authority_and_the_same_forward_plan(harness: SimpleNamespace):
    h = harness
    action, recovery = await _recovery_case(h)
    result = await h.make(authority=None, recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.PUBLISHED and result.safeguard_bundle_digest
    assert result.audit_context["effect_verified"] is False and h.authority.calls == 0
    pr = h.publisher.records[0]
    assert pr.patch == h.patch.rollback and pr.patch_path == h.patch.path
    assert pr.metadata["source_digest"] == h.patch.result_digest
    assert pr.metadata["result_digest"] == h.patch.source_digest
    assert action.action_type != h.plan.action_type and recovery.admission.await_count == 2


@pytest.mark.parametrize("missing", [True, False])
async def test_forward_approval_never_authorizes_restore(harness: SimpleNamespace, missing: bool):
    h = harness
    action, _ = await _recovery_case(h)
    recovery = None if missing else SimpleNamespace(admission=AsyncMock(return_value=None))
    result = await h.make(recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert h.authority.calls == h.publisher.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("action_digest", "sha256:" + "f" * 64),
        ("plan_digest", "sha256:" + "f" * 64),
        ("rollback_ref", "sha256:" + "f" * 64),
        ("dry_run_digest", "sha256:" + "f" * 64),
        ("executor_ref", "person:other"),
        ("synthetic", True),
    ],
)
async def test_recovery_receipt_cannot_be_rebound(harness: SimpleNamespace, field, value) -> None:
    h = harness
    action, recovery = await _recovery_case(h)
    receipt = recovery.admission.return_value
    recovery.admission.return_value = receipt.model_copy(update={field: value})
    result = await h.make(recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


@pytest.mark.parametrize("field", ["valid_until", "authorization_until"])
async def test_recovery_requires_its_own_live_interval(
    harness: SimpleNamespace, field: str
) -> None:
    h = harness
    action, recovery = await _recovery_case(h)
    receipt = recovery.admission.return_value
    recovery.admission.return_value = receipt.model_copy(update={field: h.clock[0]})
    result = await h.make(recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_recovery_revocation_at_boundary_blocks_publication(harness: SimpleNamespace) -> None:
    h = harness
    action, recovery = await _recovery_case(h)
    recovery.admission.side_effect = [recovery.admission.return_value, None]
    result = await h.make(recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert recovery.admission.await_count == 2


async def test_restore_never_overwrites_a_later_unrelated_edit(harness: SimpleNamespace) -> None:
    h = harness
    action, recovery = await _recovery_case(h)
    h.source.content = h.patch.forward + " "
    result = await h.make(recovery=recovery).execute(
        action=action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_concurrent_delivery_uses_one_shared_reservation(harness: SimpleNamespace) -> None:
    import asyncio

    h = harness
    results = await asyncio.gather(
        *(
            h.make().execute(action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL)
            for _ in range(2)
        )
    )
    assert {result.outcome for result in results} == {
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
    }
    assert h.publisher.calls == 1
    assert results[0].safeguard_bundle_digest == results[1].safeguard_bundle_digest


async def test_actual_coordinator_automation_hold_guard_cannot_be_replaced(
    harness: SimpleNamespace,
):
    h = harness
    reader = SimpleNamespace(
        read_hold_record=AsyncMock(return_value={"state": "active", "revision": 1})
    )
    coordinator, _ = _coordinator(
        h.store, commitment_store=h.commitments, hold_state_reader=reader, clock=lambda: h.clock[0]
    )
    result = await h.make(coordinator=coordinator).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    reader.read_hold_record.assert_awaited_once()


async def test_authority_lease_loss_during_final_guard_blocks_sink(
    harness: SimpleNamespace,
) -> None:
    h = harness
    reader = _AdvancingEmptyHoldReader(lambda: setattr(h.fence, "revoked", True))
    coordinator, _ = _coordinator(
        h.store, commitment_store=h.commitments, hold_state_reader=reader, clock=lambda: h.clock[0]
    )
    result = await h.make(coordinator=coordinator).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert h.fence.calls == 2


async def test_missing_workflow_commitment_is_held_by_actual_coordinator(harness: SimpleNamespace):
    h = harness
    coordinator, _ = _coordinator(h.store, clock=lambda: h.clock[0])
    result = await h.make(coordinator=coordinator).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert result.safeguard_bundle_digest is None


async def test_failed_path_intent_never_reaches_publisher(harness: SimpleNamespace) -> None:
    h = harness
    append = h.store.append_audit_entry

    async def failing_intent(entry):
        if entry.get("audit_phase") == "intent":
            raise RuntimeError("private audit outage")
        await append(entry)

    h.store.append_audit_entry = failing_intent
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert "private audit outage" not in str(h.store.audit_entries)
