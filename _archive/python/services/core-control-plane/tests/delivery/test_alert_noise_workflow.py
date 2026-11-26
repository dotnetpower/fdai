"""No-network private promotion, requester and canonical Action binding regressions.

InMemoryProcessRuntimeStore and independent-verifier fixtures are test-only. Neither
these receipts nor a bound shadow Action provide production authority or effect proof.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from fdai.core.detection.alert_noise.execution import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    alert_execution_key,
)
from fdai.core.detection.alert_noise.workflow import (
    ALERT_WORKFLOWS,
    AlertWorkflowCoordinator,
    workflow_binding_key,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.compensation import WorkflowCompensationCoordinator
from fdai.delivery.alert_noise_workflow import (
    MappedAlertRequesterReader,
    StateStoreAlertWorkflowPromotionReader,
)
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import Action, Event, Mode, RollbackRef
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessStatus
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.ontology_query import content_digest

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_workflow import (
    _SOURCE,
    _dispatched,
    _promote_actions,
    _retain_promotion,
)
from tests.core.detection.alert_noise.test_workflow import workflow_harness as workflow_harness


async def _read_promotion(h: SimpleNamespace, reader=None):
    name = ALERT_WORKFLOWS[h.plan.action_type][0]
    return await (reader or h.promotions).read(
        workflow=h.workflows[name],
        plan=h.plan,
        target_resource_id=h.plan.treatment.processing_rule_ref or h.plan.treatment.target_ref,
        now=h.clock[0],
    )


async def _next_action(h: SimpleNamespace) -> tuple[Action, Event]:
    messages = [item async for item in h.bus.subscribe("test:operator-request", "test:binder")]
    assert len(messages) == 1
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    event = EventIngest(validator=validator).ingest(messages[0].payload)
    assert event is not None
    action, _ = h.builder.build_from_operator_request(event=event)
    return action, event


async def test_missing_private_requester_is_not_replaced_with_ref_or_system_identity() -> None:
    subjects = {"person:example": str(UUID(int=1))}
    reader = MappedAlertRequesterReader(subjects=subjects)
    assert await reader.resolve(requester_ref="person:example") == str(UUID(int=1))
    assert await reader.resolve(requester_ref="person:unknown") is None
    subjects.clear()
    assert await reader.resolve(requester_ref="person:example") is None


@pytest.mark.parametrize(
    "subject",
    ["", "person:requester", "fdai.workflow", str(UUID(int=0)), True, " " + str(UUID(int=1))],
)
async def test_private_mapping_requires_exact_nonempty_oid(subject: Any) -> None:
    with pytest.raises(AlertExecutionHeld, match="mapping_invalid"):
        await MappedAlertRequesterReader(subjects={"person:example": subject}).resolve(
            requester_ref="person:example"
        )


async def test_requester_subject_never_appears_in_public_process_result(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.create(**h.inputs)
    assert str(UUID(int=1)) not in repr(result)
    raw = await h.store.read_state(workflow_binding_key(result.process_id))
    assert raw is not None and raw["context"]["requester.principal"] == str(UUID(int=1))
    audits = [row["entry"] for row in h.store.audit_entries]
    assert str(UUID(int=1)) not in repr(audits)


async def test_actual_verified_receipt_is_required_even_when_actions_are_promoted(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    _promote_actions(h)
    assert await _read_promotion(h) is None
    record = await _retain_promotion(h)
    proof = await _read_promotion(h)
    assert proof is not None and proof.receipt_digest == record["receipt_digest"]
    assert proof.evidence_digest == content_digest(record["binding"])
    assert proof.execution_authority is proof.promotion_authority is False
    unbound = StateStoreAlertWorkflowPromotionReader(
        store=h.store, admission_provider=None, source_revision=_SOURCE, clock=lambda: h.clock[0]
    )
    assert await _read_promotion(h, unbound) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "shadow"),
        ("workflow_version", "1.0.1"),
        ("workflow_digest", "sha256:" + "9" * 64),
        ("plan_digest", "sha256:" + "8" * 64),
        ("scope_digest", "sha256:" + "7" * 64),
        ("purpose_id", "workflow-approval-quorum"),
        ("source_revision", "commit:" + "b" * 40),
    ],
)
async def test_rehashed_promotion_for_other_inputs_remains_ineligible(
    workflow_harness: SimpleNamespace, field: str, value: str
) -> None:
    h = workflow_harness
    record = deepcopy(await _retain_promotion(h))
    record["binding"][field] = value
    record["evidence_digest"] = content_digest(record["binding"])
    await h.store.write_state(
        "alert-noise:workflow-promotion:" + ALERT_WORKFLOWS[h.plan.action_type][0], record
    )
    assert await _read_promotion(h) is None


async def test_full_workflow_content_not_just_name_and_version_is_admitted(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    await _retain_promotion(h)
    name = ALERT_WORKFLOWS[h.plan.action_type][0]
    original = h.workflows[name]
    h.workflows[name] = original.model_copy(
        update={"description": "Same version with different release bytes."}
    )
    assert await _read_promotion(h) is None
    assert h.workflows[name].version == original.version


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", True),
        ("synthetic", 0),
        ("execution_authority", True),
        ("completeness_basis_points", 9999),
        ("source_revision", "commit:other"),
        ("scope_digest", "sha256:" + "f" * 64),
        ("conflict_status", "unknown"),
    ],
)
async def test_non_authoritative_or_changed_receipt_cannot_promote(
    workflow_harness: SimpleNamespace, field: str, value: Any
) -> None:
    h = workflow_harness
    record = deepcopy(await _retain_promotion(h))
    record["receipt"][field] = value
    body = {key: item for key, item in record["receipt"].items() if key != "receipt_digest"}
    record["receipt"]["receipt_digest"] = content_digest(body)
    record["receipt_digest"] = record["receipt"]["receipt_digest"]
    await h.store.write_state(
        "alert-noise:workflow-promotion:" + ALERT_WORKFLOWS[h.plan.action_type][0], record
    )
    assert await _read_promotion(h) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_digest", "sha256:" + "f" * 64),
        ("evidence_digest", "sha256:" + "e" * 64),
        ("scope_digest", "sha256:" + "c" * 64),
        ("purpose_id", "other-purpose"),
        ("source_revision", "commit:other"),
    ],
)
async def test_independent_admission_must_bind_exact_receipt_and_inputs(
    workflow_harness: SimpleNamespace, field: str, value: str
) -> None:
    h = workflow_harness
    await _retain_promotion(h)

    class MismatchedAdmission:
        """Deliberate test-only verifier error, not a production admission provider."""

        async def admit(self, **kwargs: Any):
            proof = await h.admissions.admit(**kwargs)
            assert proof is not None
            return replace(proof, **{field: value})

    reader = StateStoreAlertWorkflowPromotionReader(
        store=h.store,
        admission_provider=MismatchedAdmission(),
        source_revision=_SOURCE,
        clock=lambda: h.clock[0],
    )
    assert await _read_promotion(h, reader) is None


async def test_promotion_replaced_during_independent_admission_is_not_used(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    record = await _retain_promotion(h)
    key = "alert-noise:workflow-promotion:" + ALERT_WORKFLOWS[h.plan.action_type][0]

    class RevokedDuringAdmission:
        async def admit(self, **kwargs: Any):
            proof = await h.admissions.admit(**kwargs)
            await h.store.write_state(key, {**record, "revoked": True})
            return proof

    reader = StateStoreAlertWorkflowPromotionReader(
        store=h.store,
        admission_provider=RevokedDuringAdmission(),
        source_revision=_SOURCE,
        clock=lambda: h.clock[0],
    )
    assert await _read_promotion(h, reader) is None


async def test_expired_independent_admission_never_reuses_fresh_receipt(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    await _retain_promotion(h)
    h.clock[0] += timedelta(minutes=6)
    assert await _read_promotion(h) is None


@pytest.mark.parametrize(
    "workflow_harness", ["routing", "suppression", "evaluation"], indirect=True
)
async def test_binder_uses_actual_operator_action_and_changes_only_three_fields(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    assert action.mode is Mode.SHADOW and action.rollback_ref.reference is None
    assert action.idempotency_key.startswith("operator:") and action.executor_identity_ref is None
    bound = await h.binder.bind(action, event)
    excluded = {"action_id", "idempotency_key", "rollback_ref"}
    assert bound.model_dump(exclude=excluded) == action.model_dump(exclude=excluded)
    key = alert_execution_key(action.action_type, digest_record(h.plan))
    assert bound.idempotency_key == key
    assert bound.action_id == uuid5(NAMESPACE_URL, f"fdai.action://{key}")
    assert bound.rollback_ref == RollbackRef(
        kind=action.rollback_ref.kind, reference=h.plan.rollback_ref
    )
    assert bound.mode is Mode.SHADOW and bound.executor_identity_ref is None
    assert await h.binder.bind(bound, event) == bound


async def test_non_alert_action_is_returned_unchanged_without_store_reads(
    workflow_harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    unrelated = action.model_copy(
        update={"action_type": "ops.restart-service", "action_type_ref": None}
    )

    async def forbidden(**kwargs: Any):
        raise AssertionError("non-alert binding must not read alert Process state")

    monkeypatch.setattr(h.coordinator, "resolve", forbidden)
    assert await h.binder.bind(unrelated, event) is unrelated


@pytest.mark.parametrize(
    "change",
    [
        "target",
        "padded_target",
        "mode",
        "catalog",
        "rollback",
        "count",
        "params",
        "requester",
        "correlation",
        "event_id",
        "lineage",
    ],
)
async def test_binder_holds_forged_action_event_or_private_identity(
    workflow_harness: SimpleNamespace, change: str
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    if change == "target":
        # Matching wrong targets must not silently redirect from the rule to its monitored Resource.
        action = action.model_copy(update={"target_resource_ref": h.evidence.rules[0].resource_ref})
        event = event.model_copy(update={"resource_ref": h.evidence.rules[0].resource_ref})
    elif change == "padded_target":
        action = action.model_copy(update={"target_resource_ref": " " + action.target_resource_ref})
    elif change == "mode":
        action = action.model_copy(update={"mode": Mode.ENFORCE})
    elif change == "catalog":
        action = action.model_copy(update={"action_type_ref": None})
    elif change == "rollback":
        action = action.model_copy(
            update={
                "rollback_ref": action.rollback_ref.model_copy(
                    update={"reference": "sha256:" + "9" * 64}
                )
            }
        )
    elif change == "count":
        action = action.model_copy(
            update={"blast_radius": action.blast_radius.model_copy(update={"count": 2})}
        )
    elif change == "params":
        action = action.model_copy(update={"params": {**action.params, "actor": "Thor"}})
    elif change == "requester":
        event = event.model_copy(
            update={
                "payload": {
                    **event.payload,
                    "operator_request": {
                        **event.payload["operator_request"],
                        "initiator_principal": "person:requester",
                    },
                }
            }
        )
    elif change == "correlation":
        event = event.model_copy(update={"correlation_id": "correlation:unrelated"})
    elif change == "event_id":
        action = action.model_copy(update={"event_id": UUID(int=9)})
    else:
        action = action.model_copy(update={"workflow_action": None})
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(action, event)
    assert h.store.audit_entries[-1]["entry"]["execution_authority"] is False


@pytest.mark.parametrize(
    "damage", ["creation", "proposal", "approval", "dispatch", "attempt", "terminal"]
)
async def test_binder_requires_exact_canonical_process_journal(
    workflow_harness: SimpleNamespace, damage: str
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    assert action.workflow_action is not None
    process_id = action.workflow_action.process_id
    journal = h.processes._events[process_id]
    if damage == "terminal":
        h.processes._snapshots[process_id] = replace(
            h.processes._snapshots[process_id], status=ProcessStatus.FAILED
        )
    else:
        kind = {
            "creation": ProcessEventKind.PROCESS_CREATED,
            "proposal": ProcessEventKind.PLANNING_PHASE_RECORDED,
            "approval": ProcessEventKind.APPROVAL_RECORDED,
            "dispatch": ProcessEventKind.ACTION_DISPATCHED,
            "attempt": ProcessEventKind.ACTION_DISPATCHED,
        }[damage]
        index = next(index for index, item in enumerate(journal) if item.kind is kind)
        if damage == "attempt":
            journal[index] = replace(journal[index], attempt=2)
        elif damage == "dispatch":
            journal[index] = replace(
                journal[index],
                payload={**journal[index].payload, "params": {"plan_digest": "f" * 64}},
            )
        else:
            journal.pop(index)
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(action, event)


async def test_unpromoted_shadow_process_cannot_supply_an_execution_event(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.run(**h.inputs)
    context = (await h.coordinator.resolve(process_id=result.process_id)).binding.context
    # Deliberately bypass the canonical runner to simulate forged typed ingress;
    # the binder refuses it.
    await EventBusWorkflowActionDispatcher(h.bus, "test:operator-request").dispatch(
        process_id=result.process_id,
        correlation_id=h.inputs["correlation_id"],
        step=RunbookStep(id="update_routing", action_type=h.plan.action_type),
        target_resource_id=h.evidence.rules[0].ref,
        params={"plan_digest": h.inputs["plan_digest"][7:]},
        context=context,
    )
    action, event = await _next_action(h)
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(action, event)


async def test_requester_revocation_during_promotion_is_rechecked_before_binding_returns(
    workflow_harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    original = h.promotions.read

    async def revoke(**kwargs: Any):
        proof = await original(**kwargs)
        h.subjects.clear()
        return proof

    monkeypatch.setattr(h.promotions, "read", revoke)
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(action, event)


async def test_action_promotion_loss_holds_before_risk(workflow_harness: SimpleNamespace) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    h.registry.demote(action.action_type)
    with pytest.raises(AlertExecutionHeld, match="promotion_not_current"):
        await h.binder.bind(action, event)


@pytest.mark.parametrize("change", ["expiry", "demotion", "catalog"])
async def test_promotion_is_rechecked_after_binding_audit_io(
    workflow_harness: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    original = h.store.append_audit_entry

    async def changed_after_audit(entry):
        await original(entry)
        if (
            entry.get("action_kind") == "alert_noise.action_binding"
            and entry.get("reason") == "bound"
        ):
            if change == "expiry":
                h.clock[0] += timedelta(minutes=6)
            elif change == "demotion":
                h.registry.demote(action.action_type)
            else:
                h.registered.pop(action.action_type)

    monkeypatch.setattr(h.store, "append_audit_entry", changed_after_audit)
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(action, event)


async def test_restore_binds_canonical_compensation_not_expired_forward_consent(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    # A short test plan lets forward evidence expire
    # while the distinct promotion proof remains current.
    h.plan = h.plan.model_copy(update={"expires_at": h.clock[0] + timedelta(seconds=1)})
    h.inputs["plan_digest"] = digest_record(h.plan)
    await h.store.write_state(
        "alert-noise:plan:" + digest_record(h.plan), h.plan.model_dump(mode="json")
    )
    forward, forward_event = await _dispatched(h)
    assert forward.workflow_action is not None
    process_id, step_id = forward.workflow_action.process_id, forward.workflow_action.step_id
    resolution = await h.coordinator.resolve(process_id=process_id)
    snapshot = resolution.snapshot
    # Explicit test-only independent-effect observation in the canonical journal; no provider ran.
    applied = await h.processes.transition(
        process_id=process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.RUNNING,
        current_step=step_id,
        event=ProcessEvent(
            event_id="test:effect-closed",
            process_id=process_id,
            kind=ProcessEventKind.STEP_COMPLETED,
            idempotency_key="test:effect-closed",
            recorded_at=h.clock[0],
            correlation_id=snapshot.correlation_id,
            step_id=step_id,
            payload={
                "reason": "action_effect_verified",
                "safeguard_bundle_digest": "sha256:" + "b" * 64,
            },
        ),
    )
    recovery = WorkflowCompensationCoordinator(
        process_store=h.processes,
        audit_store=h.store,
        dispatcher=EventBusWorkflowActionDispatcher(h.bus, "test:operator-request"),
        outcome_verifier=None,
    )
    started = await recovery.start(
        snapshot=applied,
        compensations={step_id: RESTORE_ACTION},
        target_resource_id=snapshot.target_resource_id,
        context=resolution.binding.context,
    )
    assert started is not None and started.snapshot.status is ProcessStatus.COMPENSATING
    restore, event = await _next_action(h)
    h.clock[0] += timedelta(seconds=2)
    with pytest.raises(AlertExecutionHeld):
        await h.binder.bind(forward, forward_event)
    bound = await h.binder.bind(restore, event)
    assert bound.action_type == RESTORE_ACTION and bound.mode is Mode.SHADOW
    assert bound.params == forward.params and bound.rollback_ref.reference == h.plan.rollback_ref
    assert bound.executor_identity_ref is None
    assert bound.idempotency_key == alert_execution_key(RESTORE_ACTION, digest_record(h.plan))
    assert bound.idempotency_key != alert_execution_key(h.plan.action_type, digest_record(h.plan))
    # Actual recovery permission remains the execution adapter's independently admitted envelope.


async def test_failed_private_record_write_never_invokes_orchestrator(
    workflow_harness: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = workflow_harness
    original = h.store.write_state_with_audit_if_absent

    async def fail_binding(key, value, audit_entry):
        if key.startswith("alert-noise:workflow:"):
            raise RuntimeError("test-only unavailable private store")
        return await original(key, value, audit_entry)

    monkeypatch.setattr(h.store, "write_state_with_audit_if_absent", fail_binding)
    with pytest.raises(RuntimeError):
        await AlertWorkflowCoordinator(**h.options).run(**h.inputs)
    assert await h.processes.list() == ()
