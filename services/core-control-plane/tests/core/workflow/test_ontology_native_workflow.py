"""Tests for Area A (Items 1-6): Ontology-native workflow primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.workflow.ontology_native import (
    ForEachObjectSetRunner,
    ObjectSetWorkflowInput,
    OntologyConditionTriggerEvaluator,
    OntologyOwnershipApprovalResolver,
    StepFunctionOutput,
    evaluate_ontology_decision_branch,
    resolve_step_output_params,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def test_item1_object_set_workflow_input_requires_complete_non_truncated_snapshot() -> None:
    objs = (
        OntologyObjectRecord(
            id="vm-2", object_type="Resource", properties={"id": "vm-2", "type": "compute"}
        ),
        OntologyObjectRecord(
            id="vm-1", object_type="Resource", properties={"id": "vm-1", "type": "compute"}
        ),
    )
    snap = OntologyGraphSnapshot(objects=objs, source_complete=True, source_generation="gen-1")
    bound = ObjectSetWorkflowInput.from_snapshot(
        snap, object_type="Resource", receipt_digest=DIGEST
    )
    assert bound.member_ids == ("vm-1", "vm-2")
    assert bound.source_generation == "gen-1"

    incomplete = OntologyGraphSnapshot(objects=objs, source_complete=False)
    with pytest.raises(ValueError, match="complete"):
        ObjectSetWorkflowInput.from_snapshot(
            incomplete, object_type="Resource", receipt_digest=DIGEST
        )


async def test_item2_for_each_object_set_runner_isolates_partial_failures() -> None:
    objs = tuple(
        OntologyObjectRecord(
            id=f"vm-{i}", object_type="Resource", properties={"id": f"vm-{i}", "type": "compute"}
        )
        for i in range(1, 4)
    )
    bound = ObjectSetWorkflowInput.from_snapshot(
        OntologyGraphSnapshot(objects=objs, source_complete=True),
        object_type="Resource",
        receipt_digest=DIGEST,
    )

    async def _handler(member_id: str) -> str:
        if member_id == "vm-2":
            raise RuntimeError("transient error")
        return f"ok:{member_id}"

    runner = ForEachObjectSetRunner(max_concurrency=2, fail_fast=False)
    receipt = await runner.run(bound, _handler)
    assert receipt.succeeded_count == 2
    assert receipt.failed_count == 1
    assert receipt.batch_digest.startswith("sha256:")


def test_item3_and_item4_step_output_binding_and_decision_branching() -> None:
    step_out = StepFunctionOutput(
        step_id="assess_risk",
        function_ref="decision.change_risk",
        receipt_digest=DIGEST,
        values={"tier": "low", "points": 1, "complete": True},
    )
    params = {
        "target_tier": "${step.assess_risk.output.tier}",
        "risk_points": "${step.assess_risk.output.points}",
        "literal": "unchanged",
    }
    resolved = resolve_step_output_params(params, {"assess_risk": step_out})
    assert resolved == {"target_tier": "low", "risk_points": 1, "literal": "unchanged"}

    chosen = evaluate_ontology_decision_branch(
        declared_outcomes=("proceed_fast", "require_quorum", "abort"),
        step_output=step_out,
        field_name="tier",
        value_to_outcome={"low": "proceed_fast", "medium": "require_quorum", "high": "abort"},
    )
    assert chosen == "proceed_fast"

    incomplete_out = StepFunctionOutput(
        step_id="assess_risk",
        function_ref="decision.change_risk",
        receipt_digest=DIGEST,
        values={"tier": "low", "complete": False},
    )
    with pytest.raises(ValueError, match="incomplete"):
        evaluate_ontology_decision_branch(
            declared_outcomes=("proceed_fast",),
            step_output=incomplete_out,
            field_name="tier",
            value_to_outcome={"low": "proceed_fast"},
        )


def test_item5_condition_trigger_fires_once_on_rising_edge() -> None:
    evaluator = OntologyConditionTriggerEvaluator(trigger_id="trig.high-burn")

    first = evaluator.evaluate_transition(
        member_id="svc-1",
        condition_satisfied=True,
        complete=True,
        receipt_digest=DIGEST,
        observed_at=NOW,
    )
    assert first is not None
    assert first.idempotency_key.startswith("cond-trigger:sha256:")

    # Still true -> does not re-fire
    second = evaluator.evaluate_transition(
        member_id="svc-1",
        condition_satisfied=True,
        complete=True,
        receipt_digest=DIGEST,
        observed_at=NOW + timedelta(minutes=1),
    )
    assert second is None

    # Resets when false, then fires again on next rising edge
    evaluator.evaluate_transition(
        member_id="svc-1",
        condition_satisfied=False,
        complete=True,
        receipt_digest=DIGEST,
        observed_at=NOW + timedelta(minutes=2),
    )
    third = evaluator.evaluate_transition(
        member_id="svc-1",
        condition_satisfied=True,
        complete=True,
        receipt_digest=DIGEST,
        observed_at=NOW + timedelta(minutes=3),
    )
    assert third is not None


async def test_item6_dynamic_ownership_approval_resolver_traverses_service_graph() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types, link_types=catalog.link_types
    )
    long_ago = NOW - timedelta(days=30)
    await store.upsert_object(
        OntologyObjectRecord(
            id="res-db", object_type="Resource", properties={"id": "res-db", "type": "compute"}
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="wl- checkout",
            object_type="Workload",
            properties={
                "id": "wl- checkout",
                "name": "checkout-api",
                "workload_kind": "service",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="svc-checkout",
            object_type="BusinessService",
            properties={
                "id": "svc-checkout",
                "name": "Checkout",
                "criticality": "critical",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="own-checkout",
            object_type="Ownership",
            properties={
                "id": "own-checkout",
                "owner_ref": "team:checkout-owners",
                "escalation_ref": "oncall:checkout-primary",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        )
    )
    await store.upsert_link(OntologyLinkRecord("workload_runs_on", "wl- checkout", "res-db"))
    await store.upsert_link(OntologyLinkRecord("implemented_by", "svc-checkout", "wl- checkout"))
    await store.upsert_link(OntologyLinkRecord("service_owned_by", "svc-checkout", "own-checkout"))

    resolver = OntologyOwnershipApprovalResolver(store)
    resolved = await resolver.resolve(target_resource_ref="res-db", at=NOW)
    assert resolved is not None
    assert resolved.service_refs == ("svc-checkout",)
    assert resolved.owner_refs == ("team:checkout-owners",)
    assert resolved.escalation_refs == ("oncall:checkout-primary",)


async def test_ontology_aware_workflow_runtime_wires_briefing_recovery_ownership_and_wave5() -> (
    None
):
    import yaml
    from fdai.core.measurement.closed_loop_governance import WorkflowScaleSafetyController
    from fdai.core.notifications.matrix import load_matrix_from_yaml
    from fdai.core.rbac.resolver import GroupMapping
    from fdai.core.workflow import (
        OntologyAwareWorkflowRuntime,
        WorkflowApprovalPlanner,
        WorkflowOrchestrator,
    )
    from fdai.rule_catalog.schema.action_type import load_action_type_catalog
    from fdai.rule_catalog.schema.workflow import load_workflow_catalog
    from fdai.shared.providers.process_runtime import ProcessStatus
    from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    registry = PackageResourceSchemaRegistry()
    actions = {
        a.name: a
        for a in load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=registry,
            probes_root=REPO_ROOT / "rule-catalog" / "probes",
        )
    }
    workflows = {
        w.name: w
        for w in load_workflow_catalog(
            REPO_ROOT / "rule-catalog" / "workflows",
            schema_registry=registry,
            action_type_names=set(actions),
        )
    }
    with (REPO_ROOT / "config" / "rbac-groups.yaml").open(encoding="utf-8") as handle:
        group_mapping = GroupMapping.from_config(yaml.safe_load(handle))
    planner = WorkflowApprovalPlanner(
        action_types=actions,
        group_mapping=group_mapping,
        matrix=load_matrix_from_yaml(REPO_ROOT / "config" / "notifications-matrix.yaml"),
    )

    class _ToggleGuard:
        def __init__(self, allow: bool) -> None:
            self.allow = allow

        async def evaluate(self, **_: object) -> bool:
            return self.allow

    state_store = InMemoryStateStore()
    orch_allow = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=state_store,
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=_ToggleGuard(True),
    )
    runtime_allow = OntologyAwareWorkflowRuntime(
        orchestrator=orch_allow,
        state_store=state_store,
        scale_safety=WorkflowScaleSafetyController(state_store, max_active_per_scope=2),
    )
    now_ts = datetime.now(tz=UTC)
    outcome_ok = await runtime_allow.execute(
        workflows["blast-radius-gated-service-restart"],
        scope_ref="scope-1",
        target_resource_id="res-db",
        trigger_ts=now_ts,
        context={"requester.principal": "operator-1", "change.reason": "healthy"},
    )
    assert outcome_ok.run is not None
    assert outcome_ok.run.status is ProcessStatus.WAITING
    assert outcome_ok.approver_briefing is not None
    stored_brief = await state_store.read_state(
        f"workflow:approver-briefing:{outcome_ok.run.process_id}"
    )
    assert stored_brief is not None

    # Blocked gate triggers abstention recovery plan persistence
    orch_deny = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=state_store,
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=_ToggleGuard(False),
    )
    runtime_deny = OntologyAwareWorkflowRuntime(
        orchestrator=orch_deny,
        state_store=state_store,
    )
    outcome_deny = await runtime_deny.execute(
        workflows["blast-radius-gated-service-restart"],
        scope_ref="scope-1",
        target_resource_id="res-db-2",
        trigger_ts=now_ts,
        context={"requester.principal": "operator-1", "change.reason": "blocked"},
        abstention_reason_codes=("criticality_unreviewed",),
    )
    assert outcome_deny.run is not None
    assert outcome_deny.run.status is ProcessStatus.FAILED
    assert outcome_deny.abstention_recovery_plan is not None
    assert (
        "probe.service_catalog_criticality_sync"
        in outcome_deny.abstention_recovery_plan.required_probes
    )
