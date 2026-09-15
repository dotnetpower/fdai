"""Canonical alert Process mechanics, not live approval or promotion evidence.

All stores, subjects and verification proofs here are explicit no-network unit
fixtures. Production-shaped receipts test admission mechanics only. These tests
must never be used as a deployed promotion record or a production composition.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml
from fdai.core.detection.alert_noise.execution import (
    ALERT_ACTIONS,
    RESTORE_ACTION,
    AlertExecutionHeld,
)
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.detection.alert_noise.workflow import (
    ALERT_WORKFLOW_PROMOTION_PURPOSE,
    PLAN_CONTEXT_KEY,
    AlertWorkflowCoordinator,
    alert_decision_case,
    workflow_binding_key,
    workflow_promotion_binding,
)
from fdai.core.event_ingest import EventIngest
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.risk_gate.gate import ActionPromotionRegistry, PromotionMetrics
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.approval_admission import (
    WORKFLOW_APPROVAL_EVIDENCE_PURPOSE,
    workflow_approval_evidence_digest,
    workflow_approval_scope_digest,
)
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.core.workflow.workflow_runtime import derive_process_id
from fdai.delivery.alert_noise_pr import StateStoreAlertPlanReader
from fdai.delivery.alert_noise_workflow import (
    MappedAlertRequesterReader,
    StateStoreAlertActionBinder,
    StateStoreAlertWorkflowPromotionReader,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreDecisionEvidenceAdmissionRecorder,
)
from fdai.delivery.persistence.state_store_hil_registry import StateStoreHilApprovalRegistry
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.rule_catalog.schema.workflow import load_workflow_from_mapping
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import (
    Action,
    CeilingRole,
    Event,
    Mode,
    OntologyDeclarationKind,
    Workflow,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilDuplicateApproverError,
    HilSelfApprovalForbiddenError,
)
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessStatus
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    NoisePolicy,
    ProcessingRule,
    digest_record,
)
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    LiveEvidenceClaimRequirement,
)
from fdai_service_contracts.ontology_query import content_digest
from tests.core.readiness.test_decision_evidence import _bundle, _gate, _receipt

_ROOT = Path(__file__).resolve().parents[6]
_SOURCE = "commit:" + "a" * 40


@pytest.fixture
async def workflow_harness(
    now: datetime,
    evidence: AlertEvidence,
    request: pytest.FixtureRequest,
) -> SimpleNamespace:
    """Bind the actual runtime and catalog; only stores and proof sources are unit fakes."""
    clock = [now]
    # Exercise live-shape rejection/acceptance in this test only; no real receipt exists.
    evidence = evidence.model_copy(
        update={"stamp": evidence.stamp.model_copy(update={"synthetic": False})}
    )
    kind = getattr(request, "param", "routing")
    validation = None
    treatment = AlertTreatment(
        kind="routing",
        target_ref="rule:example",
        remove_group_ref="group:old",
        replacement_group_ref="group:new",
    )
    if kind == "suppression":
        processing = ProcessingRule(
            ref="processing:example",
            revision="sha256:" + "f" * 64,
            rule_refs=("rule:example",),
            action="suppress",
            enabled=False,
            effective_from=now,
            effective_to=now + timedelta(hours=2),
            semantics_complete=True,
        )
        evidence = evidence.model_copy(update={"processing_rules": (processing,)})
        treatment = AlertTreatment(
            kind="suppression",
            target_ref="rule:example",
            processing_rule_ref=processing.ref,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
    elif kind == "evaluation":
        baseline = evidence.rules[0].evaluation
        assert baseline is not None
        changed = baseline.model_copy(update={"threshold": 85.0})
        treatment = AlertTreatment(kind="evaluation", target_ref="rule:example", evaluation=changed)
        validation = EvaluationReceipt(
            rule_ref="rule:example",
            rule_revision=evidence.rules[0].revision,
            scenario_digest="sha256:" + "e" * 64,
            baseline=baseline,
            treatment=changed,
            evaluated_at=now,
            expires_at=now + timedelta(hours=1),
            baseline_true_positive=1,
            treatment_true_positive=1,
            baseline_false_positive=1,
            treatment_false_positive=0,
            baseline_false_negative=0,
            treatment_false_negative=0,
            accepted=True,
            reason="accepted",
        )
    plan = plan_alert_change(
        evidence,
        treatment,
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
        evaluation_receipt=validation,
    )
    store = InMemoryStateStore(linearization_clock=lambda: clock[0])
    await store.write_state("alert-noise:plan:" + digest_record(plan), plan.model_dump(mode="json"))
    await store.write_state(
        "alert-noise:evidence:" + plan.evidence_digest, evidence.model_dump(mode="json")
    )
    schema = PackageResourceSchemaRegistry()
    actions = {}
    for name in sorted(ALERT_ACTIONS):
        with (_ROOT / "rule-catalog" / "action-types" / f"{name}.yaml").open(
            encoding="utf-8"
        ) as stream:
            actions[name] = load_action_type_from_mapping(
                yaml.safe_load(stream), schema_registry=schema
            )
    workflows = {}
    for name in (
        "alert-routing-change",
        "alert-notification-window-change",
        "alert-evaluation-change",
    ):
        with (_ROOT / "rule-catalog" / "workflows" / f"{name}.yaml").open(
            encoding="utf-8"
        ) as stream:
            workflows[name] = load_workflow_from_mapping(
                yaml.safe_load(stream), schema_registry=schema, action_type_names=set(actions)
            )
    planner = WorkflowApprovalPlanner(
        action_types=actions,
        group_mapping=GroupMapping(
            reader_group_id="group:readers",
            contributor_group_id="group:contributors",
            approver_group_id="group:approvers",
            owner_group_id="group:owners",
            break_glass_group_id="group:break-glass",
        ),
        matrix=load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": "a1_hil_approval",
                            "primary": "test-hil",
                            "fallback": [],
                        },
                    },
                },
            }
        ),
    )
    processes, bus = InMemoryProcessRuntimeStore(), InMemoryEventBus()
    admissions = StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: clock[0])
    approvals = StateStoreWorkflowApprovalProvider(store)
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=store,
        process_store=processes,
        approval_provider=approvals,
        approval_decision_evidence_provider=admissions,
        action_dispatcher=EventBusWorkflowActionDispatcher(bus, "test:operator-request"),
    )
    subjects = {plan.requester_ref: str(UUID(int=1))}
    requesters = MappedAlertRequesterReader(subjects=subjects)
    promotions = StateStoreAlertWorkflowPromotionReader(
        store=store, admission_provider=admissions, source_revision=_SOURCE, clock=lambda: clock[0]
    )
    # Explicit test-only legacy-metrics mode; production defaults remain fail closed.
    registry = ActionPromotionRegistry(allow_legacy_metrics=True)
    options = dict(
        plans=StateStoreAlertPlanReader(store=store),
        requesters=requesters,
        workflows=workflows,
        action_types=actions,
        registry=registry,
        promotions=promotions,
        orchestrator=orchestrator,
        process_store=processes,
        store=store,
        source_revision=_SOURCE,
        clock=lambda: clock[0],
    )
    coordinator = AlertWorkflowCoordinator(**options)
    release = build_ontology_release(action_types=tuple(actions.values()))
    registered = {name: release.type_ref(OntologyDeclarationKind.ACTION, name) for name in actions}
    return SimpleNamespace(
        plan=plan,
        evidence=evidence,
        clock=clock,
        store=store,
        workflows=workflows,
        actions=actions,
        processes=processes,
        bus=bus,
        admissions=admissions,
        approvals=approvals,
        subjects=subjects,
        requesters=requesters,
        promotions=promotions,
        registry=registry,
        options=options,
        coordinator=coordinator,
        orchestrator=orchestrator,
        planner=planner,
        registered=registered,
        release=release,
        hil=StateStoreHilApprovalRegistry(store=store, clock=lambda: clock[0]),
        binder=StateStoreAlertActionBinder(
            workflows=coordinator,
            registered_actions=registered,
            store=store,
            clock=lambda: clock[0],
        ),
        builder=ActionBuilder(
            action_types_by_name=actions, ontology_release=release, clock=lambda: clock[0]
        ),
        inputs=dict(
            plan_digest=digest_record(plan),
            evidence_digest=plan.evidence_digest,
            correlation_id="correlation:alert-example",
        ),
    )


async def _retain_admission(
    h: SimpleNamespace,
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
) -> DecisionCriticalEvidenceReceipt:
    """Use existing test-only independent proofs with the actual readiness and durable APIs."""
    now = h.clock[0]
    receipt = _receipt(
        evidence_digest=evidence_digest,
        scope_digest=scope_digest,
        purpose_id=purpose_id,
        source_revision=source_revision,
        event_at=now,
        evidence_cutoff=now,
        recorded_at=now,
        fresh_until=now + timedelta(hours=1),
        freshness_ceiling_seconds=3600,
    )
    requirement = LiveEvidenceClaimRequirement(
        allowed_authority_classes=(receipt.authority_class,),
        allowed_source_identities=(receipt.source_identity,),
        scope_digest=receipt.scope_digest,
        purpose_id=receipt.purpose_id,
        producer_id=receipt.producer_id,
        producer_version=receipt.producer_version,
        method_id=receipt.method_id,
        method_version=receipt.method_version,
        source_revision=receipt.source_revision,
        freshness_policy_digest=receipt.freshness_policy_digest,
        freshness_ceiling_seconds=3600,
    )
    bundle = _bundle(receipt, verified_at=now, valid_until=now + timedelta(minutes=5))
    result = await _gate(receipt, bundle=bundle).evaluate(receipt, requirement, evaluated_at=now)
    assert result.eligible and result.admission is not None
    await StateStoreDecisionEvidenceAdmissionRecorder(
        store=h.store, clock=lambda: h.clock[0]
    ).retain(receipt, result)
    return receipt


def _promote_actions(h: SimpleNamespace, *, include_restore: bool = True) -> None:
    for name in (h.plan.action_type, RESTORE_ACTION) if include_restore else (h.plan.action_type,):
        declaration = h.actions[name]
        gate = declaration.promotion_gate
        h.registry.consider_promotion(
            action_type=declaration,
            metrics=PromotionMetrics(
                action_type=name,
                shadow_days=gate.min_shadow_days,
                samples=gate.min_samples,
                accuracy=gate.min_accuracy,
                policy_escapes=0,
            ),
        )


async def _retain_promotion(h: SimpleNamespace) -> dict[str, Any]:
    name = {
        "routing": "alert-routing-change",
        "suppression": "alert-notification-window-change",
        "evaluation": "alert-evaluation-change",
    }[h.plan.treatment.kind]
    target = h.plan.treatment.processing_rule_ref or h.plan.treatment.target_ref
    binding = workflow_promotion_binding(
        workflow=h.workflows[name], plan=h.plan, target_resource_id=target, source_revision=_SOURCE
    )
    receipt = await _retain_admission(
        h,
        evidence_digest=content_digest(binding),
        scope_digest=str(binding["scope_digest"]),
        purpose_id=ALERT_WORKFLOW_PROMOTION_PURPOSE,
        source_revision=_SOURCE,
    )
    record = {
        "binding": binding,
        "evidence_digest": receipt.evidence_digest,
        "receipt_digest": receipt.receipt_digest,
        "receipt": receipt.model_dump(mode="json"),
    }
    await h.store.write_state("alert-noise:workflow-promotion:" + name, record)
    return record


async def _approve(h: SimpleNamespace, process_id: str, *, admit: bool = True) -> None:
    pending = await h.hil.list_pending()
    assert len(pending) == 2
    for slot, subject in zip(pending, (str(UUID(int=2)), str(UUID(int=3))), strict=True):
        await h.hil.record_decision(
            idempotency_key=slot.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=subject,
        )
    if admit:
        snapshot = await h.approvals.read_snapshot(process_id=process_id, step_id="approve_plan")
        assert snapshot is not None
        await _retain_admission(
            h,
            evidence_digest=workflow_approval_evidence_digest(
                snapshot, quorum=2, no_self_approval=True
            ),
            scope_digest=workflow_approval_scope_digest(snapshot),
            purpose_id=WORKFLOW_APPROVAL_EVIDENCE_PURPOSE,
            source_revision=f"workflow-approval-revision:{snapshot.revision}",
        )


async def _dispatched(h: SimpleNamespace) -> tuple[Action, Event]:
    """Exercise real Var decisions, canonical dispatch, ingress normalization and ActionBuilder."""
    _promote_actions(h)
    await _retain_promotion(h)
    initial = await h.coordinator.run(**h.inputs)
    await _approve(h, initial.process_id)
    result = await h.coordinator.resume(process_id=initial.process_id)
    assert result.status is ProcessStatus.WAITING and result.mode is Mode.ENFORCE
    messages = [
        message async for message in h.bus.subscribe("test:operator-request", "test:binder")
    ]
    assert len(messages) == 1
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    event = EventIngest(validator=validator).ingest(messages[0].payload)
    assert event is not None
    action, _ = h.builder.build_from_operator_request(event=event)
    return action, event


@pytest.mark.parametrize(
    "workflow_harness", ["routing", "suppression", "evaluation"], indirect=True
)
async def test_shadow_runs_canonical_process_without_approval_or_action(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.run(**h.inputs)
    snapshot = await h.processes.get(result.process_id)
    assert snapshot is not None and snapshot.status is ProcessStatus.WAITING
    target = h.plan.treatment.processing_rule_ref or h.evidence.rules[0].ref
    assert snapshot.target_resource_id == target != h.evidence.rules[0].resource_ref
    assert snapshot.current_step == "approve_plan"
    assert result.mode is Mode.SHADOW and result.process_ref == "process:" + result.process_id
    assert (
        result.execution_authority
        is result.approval_authority
        is result.promotion_authority
        is False
    )
    assert result.process_id == derive_process_id(
        workflow_name=result.workflow_ref, target_resource_id=target, trigger_ts=h.plan.created_at
    )
    events = await h.processes.events(result.process_id)
    assert events[0].kind is ProcessEventKind.PROCESS_CREATED
    assert events[1].kind is ProcessEventKind.PLANNING_PHASE_RECORDED
    assert not any(
        item.kind in {ProcessEventKind.ACTION_DISPATCHED, ProcessEventKind.APPROVAL_RECORDED}
        for item in events
    )
    assert [
        item.payload["decision"]
        for item in events
        if item.kind is ProcessEventKind.APPROVAL_REQUESTED
    ] == ["pending"]
    assert await h.hil.list_pending() == ()
    assert [item async for item in h.bus.subscribe("test:operator-request", "test:shadow")] == []
    with pytest.raises(FrozenInstanceError):
        result.mode = Mode.ENFORCE


async def test_records_real_proposal_and_no_action_not_invented_benefit(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.create(**h.inputs)
    assert result.status is ProcessStatus.PENDING
    resolved = await h.coordinator.resolve(process_id=result.process_id)
    case = alert_decision_case(resolved.binding, h.plan)
    assert case.process_id == result.process_id and case.options[0].action_type is None
    assert case.options[1].arguments is not None
    assert case.options[1].arguments.values() == {"plan_digest": h.inputs["plan_digest"][7:]}
    assert {effect.utility for option in case.options for effect in option.effects} == {0.0}
    assert {effect.metric for option in case.options for effect in option.effects} == {
        "planned_changed_objects"
    }
    payload = resolved.events[1].payload
    assert (
        payload["expected_notification_benefit"] is None and payload["selected_option_id"] is None
    )
    assert payload["proposal"] == h.plan.model_dump(mode="json")
    assert payload["proposal_ref"] == "alert-noise:plan:" + h.inputs["plan_digest"]
    assert resolved.events[1].causation_id == resolved.events[0].event_id


async def test_full_private_context_is_retained_before_canonical_invocation(
    workflow_harness: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = workflow_harness
    original = WorkflowOrchestrator.run
    contexts = []

    async def capture(instance: WorkflowOrchestrator, workflow: Workflow, **kwargs: Any):
        process_id = derive_process_id(
            workflow_name=workflow.name,
            target_resource_id=kwargs["target_resource_id"],
            trigger_ts=kwargs["trigger_ts"],
        )
        raw = await h.store.read_state(workflow_binding_key(process_id))
        assert raw is not None and raw["context"] == dict(kwargs["context"])
        assert (await h.processes.events(process_id))[
            1
        ].kind is ProcessEventKind.PLANNING_PHASE_RECORDED
        contexts.append(dict(kwargs["context"]))
        return await original(instance, workflow, **kwargs)

    monkeypatch.setattr(WorkflowOrchestrator, "run", capture)
    result = await h.coordinator.run(**h.inputs)
    await AlertWorkflowCoordinator(**h.options).resume(process_id=result.process_id)
    expected = {
        "requester.principal": str(UUID(int=1)),
        "workflow.requester_principal": str(UUID(int=1)),
        PLAN_CONTEXT_KEY: h.inputs["plan_digest"].removeprefix("sha256:"),
    }
    assert contexts == [expected, expected]
    events = await h.processes.events(result.process_id)
    assert sum(item.kind is ProcessEventKind.PLANNING_PHASE_RECORDED for item in events) == 1
    assert sum(item.kind is ProcessEventKind.PROCESS_CREATED for item in events) == 1


@pytest.mark.parametrize("field", ["plan_digest", "evidence_digest"])
async def test_source_digest_must_match_retained_reader(
    workflow_harness: SimpleNamespace, field: str
) -> None:
    h = workflow_harness
    with pytest.raises(AlertExecutionHeld):
        await h.coordinator.run(**{**h.inputs, field: "sha256:" + "9" * 64})
    assert await h.processes.list() == ()


@pytest.mark.parametrize(
    "change", [{"synthetic": True}, {"coverage": "partial", "reasons": ("source_incomplete",)}]
)
async def test_synthetic_or_incomplete_retained_evidence_cannot_start(
    workflow_harness: SimpleNamespace, change: dict
) -> None:
    h = workflow_harness
    changed = h.evidence.model_copy(update={"stamp": h.evidence.stamp.model_copy(update=change)})
    await h.store.write_state(
        "alert-noise:evidence:" + h.plan.evidence_digest, changed.model_dump(mode="json")
    )
    with pytest.raises(AlertExecutionHeld):
        await h.coordinator.run(**h.inputs)
    assert await h.processes.list() == ()


@pytest.mark.parametrize("change", ["principal", "workflow", "context", "creation", "proposal"])
async def test_resume_rejects_exact_lineage_substitution(
    workflow_harness: SimpleNamespace, change: str
) -> None:
    h = workflow_harness
    result = await h.coordinator.run(**h.inputs)
    key = workflow_binding_key(result.process_id)
    if change == "principal":
        h.subjects[h.plan.requester_ref] = str(UUID(int=4))
    elif change == "workflow":
        workflow = h.workflows[result.workflow_ref]
        h.workflows[result.workflow_ref] = workflow.model_copy(
            update={"description": "Changed release content."}
        )
    elif change == "context":
        raw = dict(await h.store.read_state(key))
        raw["context"] = {**raw["context"], "approval.approve_plan.attacker": "approved"}
        raw["record_digest"] = content_digest(
            {name: value for name, value in raw.items() if name != "record_digest"}
        )
        await h.store.write_state(key, raw)
    else:
        # Deliberate test-store corruption: the production append API cannot rewrite history.
        index = 0 if change == "creation" else 1
        event = h.processes._events[result.process_id][index]
        h.processes._events[result.process_id][index] = replace(
            event, correlation_id="correlation:other"
        )
    with pytest.raises(ValueError):
        await AlertWorkflowCoordinator(**h.options).resume(process_id=result.process_id)
    assert [item async for item in h.bus.subscribe("test:operator-request", "test:tamper")] == []


async def test_same_trigger_cannot_silently_replace_plan_or_correlation(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    original = await h.coordinator.create(**h.inputs)
    changed = h.plan.model_copy(update={"max_execution_seconds": h.plan.max_execution_seconds + 1})
    await h.store.write_state(
        "alert-noise:plan:" + digest_record(changed), changed.model_dump(mode="json")
    )
    with pytest.raises(AlertExecutionHeld, match="conflict"):
        await h.coordinator.create(**{**h.inputs, "plan_digest": digest_record(changed)})
    with pytest.raises(AlertExecutionHeld, match="conflict"):
        await h.coordinator.create(**{**h.inputs, "correlation_id": "correlation:other"})
    assert (await h.coordinator.resolve(process_id=original.process_id)).plan == h.plan


async def test_parent_orchestrator_must_resolve_same_process_store(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    coordinator = AlertWorkflowCoordinator(
        **{**h.options, "process_store": InMemoryProcessRuntimeStore()}
    )
    with pytest.raises(RuntimeError, match="unknown Process"):
        await coordinator.run(**h.inputs)
    assert await h.processes.list() == ()


@pytest.mark.parametrize("missing", ["workflow", "forward", "restore"])
async def test_workflow_and_both_actual_action_promotions_are_required(
    workflow_harness: SimpleNamespace, missing: str
) -> None:
    h = workflow_harness
    if missing != "workflow":
        await _retain_promotion(h)
    _promote_actions(h, include_restore=missing != "restore")
    if missing == "forward":
        h.registry.demote(h.plan.action_type)
    result = await h.coordinator.run(**h.inputs)
    assert result.mode is Mode.SHADOW and await h.hil.list_pending() == ()


async def test_shadow_replay_never_escalates_after_later_promotion(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.run(**h.inputs)
    _promote_actions(h)
    await _retain_promotion(h)
    replay = await h.coordinator.resume(process_id=result.process_id)
    assert replay.mode is Mode.SHADOW and await h.hil.list_pending() == ()


async def test_real_var_quorum_keeps_requester_excluded_and_needs_independent_admission(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    _promote_actions(h)
    await _retain_promotion(h)
    result = await h.coordinator.run(**h.inputs)
    pending = await h.hil.list_pending()
    assert len(pending) == 2 and all(item.metadata["required_role"] == "Owner" for item in pending)
    with pytest.raises(HilSelfApprovalForbiddenError):
        await h.hil.record_decision(
            idempotency_key=pending[0].idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=str(UUID(int=1)),
        )
    await h.hil.record_decision(
        idempotency_key=pending[0].idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid=str(UUID(int=2)),
    )
    with pytest.raises(HilDuplicateApproverError):
        await h.hil.record_decision(
            idempotency_key=pending[1].idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=str(UUID(int=2)),
        )
    await h.hil.record_decision(
        idempotency_key=pending[1].idempotency_key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid=str(UUID(int=3)),
    )
    resumed = await h.coordinator.resume(process_id=result.process_id)
    assert resumed.status is ProcessStatus.FAILED
    assert [
        item async for item in h.bus.subscribe("test:operator-request", "test:unadmitted")
    ] == []


async def test_real_approved_admitted_workflow_dispatches_once_and_waits_for_effect(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    action, event = await _dispatched(h)
    assert action.workflow_action is not None
    assert action.mode is Mode.SHADOW and action.idempotency_key.startswith("operator:")
    assert action.rollback_ref.reference is None and action.executor_identity_ref is None
    assert action.target_resource_ref == h.evidence.rules[0].ref
    assert event.payload["operator_request"]["initiator_principal"] == str(UUID(int=1))
    replay = await AlertWorkflowCoordinator(**h.options).resume(
        process_id=action.workflow_action.process_id
    )
    assert replay.status is ProcessStatus.WAITING
    assert [item async for item in h.bus.subscribe("test:operator-request", "test:binder")] == []


async def test_action_demotion_holds_enforce_resume_without_changing_original_mode(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    _promote_actions(h)
    await _retain_promotion(h)
    result = await h.coordinator.run(**h.inputs)
    h.registry.demote(h.plan.action_type)
    with pytest.raises(AlertExecutionHeld, match="promotion_not_current"):
        await h.coordinator.resume(process_id=result.process_id)
    assert (await h.coordinator.resolve(process_id=result.process_id)).binding.mode is Mode.ENFORCE


async def test_expired_forward_plan_does_not_restart_with_a_new_timestamp(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.run(**h.inputs)
    h.clock[0] = h.plan.expires_at
    with pytest.raises(AlertExecutionHeld, match="not_current"):
        await h.coordinator.resume(process_id=result.process_id)
    assert len(await h.processes.list()) == 1


@pytest.mark.parametrize(
    "change", ["quorum", "role", "digest_arg", "compensation", "mode", "missing_action"]
)
async def test_workflow_cannot_widen_reviewed_catalog_shape(
    workflow_harness: SimpleNamespace, change: str
) -> None:
    h = workflow_harness
    workflow = h.workflows["alert-routing-change"]
    approval, action = workflow.steps
    if change == "quorum":
        approval = approval.model_copy(update={"quorum": 1})
    elif change == "role":
        approval = approval.model_copy(update={"approval_role": CeilingRole.CONTRIBUTOR})
    elif change == "digest_arg":
        action = action.model_copy(update={"params": {"plan_digest": "a" * 64}})
    elif change == "compensation":
        action = action.model_copy(update={"compensated_by": None})
    elif change == "missing_action":
        h.actions.pop(RESTORE_ACTION)
    h.workflows[workflow.name] = workflow.model_copy(
        update={
            "steps": [approval, action],
            "default_mode": Mode.ENFORCE if change == "mode" else Mode.SHADOW,
        }
    )
    with pytest.raises(ValueError):
        await h.coordinator.run(**h.inputs)
    assert await h.processes.list() == ()


async def test_missing_var_binding_fails_canonical_enforce_step(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    _promote_actions(h)
    await _retain_promotion(h)
    orchestrator = WorkflowOrchestrator(
        planner=h.planner,
        action_types=h.actions,
        audit_store=h.store,
        process_store=h.processes,
        action_dispatcher=EventBusWorkflowActionDispatcher(h.bus, "test:operator-request"),
    )
    coordinator = AlertWorkflowCoordinator(**{**h.options, "orchestrator": orchestrator})
    result = await coordinator.run(**h.inputs)
    assert result.status is ProcessStatus.FAILED
    assert any(
        item.payload.get("reason") == "approval_provider_not_configured"
        for item in await h.processes.events(result.process_id)
    )
    assert [
        item async for item in h.bus.subscribe("test:operator-request", "test:unbound-var")
    ] == []


async def test_promotion_expiry_after_metadata_read_blocks_enforce_invocation(
    workflow_harness: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = workflow_harness
    _promote_actions(h)
    await _retain_promotion(h)
    result = await h.coordinator.create(**h.inputs)
    original = WorkflowOrchestrator.resume_metadata

    async def delayed(instance: WorkflowOrchestrator, **kwargs: Any):
        envelope = await original(instance, **kwargs)
        h.clock[0] += timedelta(minutes=6)
        return envelope

    monkeypatch.setattr(WorkflowOrchestrator, "resume_metadata", delayed)
    with pytest.raises(AlertExecutionHeld, match="promotion_not_current"):
        await h.coordinator.resume(process_id=result.process_id)
    assert await h.hil.list_pending() == ()
    assert (await h.processes.get(result.process_id)).status is ProcessStatus.PENDING


async def test_interrupted_running_process_uses_canonical_resume(
    workflow_harness: SimpleNamespace,
) -> None:
    h = workflow_harness
    result = await h.coordinator.create(**h.inputs)
    snapshot = await h.processes.get(result.process_id)
    assert snapshot is not None
    await h.processes.transition(
        process_id=result.process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.RUNNING,
        current_step="approve_plan",
        event=ProcessEvent(
            event_id="test:interrupted-start",
            process_id=result.process_id,
            kind=ProcessEventKind.PROCESS_STARTED,
            idempotency_key="test:interrupted-start",
            recorded_at=h.clock[0],
            correlation_id=snapshot.correlation_id,
        ),
    )
    resumed = await AlertWorkflowCoordinator(**h.options).resume(process_id=result.process_id)
    assert resumed.process_id == result.process_id and resumed.status is ProcessStatus.WAITING
    assert resumed.mode is Mode.SHADOW and len(await h.processes.list()) == 1
