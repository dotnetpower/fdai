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
    now_ts = NOW
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


async def test_item1_and_item2_validation_and_fail_fast_edges() -> None:
    objs = (
        OntologyObjectRecord(
            id="vm-1", object_type="Resource", properties={"id": "vm-1", "type": "compute"}
        ),
        OntologyObjectRecord(
            id="vm-2", object_type="Resource", properties={"id": "vm-2", "type": "compute"}
        ),
    )
    snap = OntologyGraphSnapshot(objects=objs, source_complete=True)

    with pytest.raises(ValueError, match="object_type MUST be non-empty"):
        ObjectSetWorkflowInput.from_snapshot(snap, object_type="  ", receipt_digest=DIGEST)
    with pytest.raises(ValueError, match="receipt_digest MUST be SHA-256"):
        ObjectSetWorkflowInput.from_snapshot(snap, object_type="Resource", receipt_digest="bad")
    with pytest.raises(ValueError, match="max_members is outside"):
        ObjectSetWorkflowInput.from_snapshot(
            snap, object_type="Resource", receipt_digest=DIGEST, max_members=0
        )
    with pytest.raises(ValueError, match="at least one matching member"):
        ObjectSetWorkflowInput.from_snapshot(snap, object_type="Workload", receipt_digest=DIGEST)
    with pytest.raises(ValueError, match="exceeds max_members"):
        ObjectSetWorkflowInput.from_snapshot(
            snap, object_type="Resource", receipt_digest=DIGEST, max_members=1
        )
    with pytest.raises(ValueError, match=r"max_concurrency MUST be in 1\.\.64"):
        ForEachObjectSetRunner(max_concurrency=0)

    bound = ObjectSetWorkflowInput.from_snapshot(
        snap, object_type="Resource", receipt_digest=DIGEST
    )

    async def _fail_first(member_id: str) -> str:
        if member_id == "vm-1":
            raise RuntimeError("boom")
        return member_id

    runner = ForEachObjectSetRunner(max_concurrency=1, fail_fast=True)
    receipt = await runner.run(bound, _fail_first)
    assert receipt.failed_count == 2
    assert receipt.outcomes[0].error == "RuntimeError:boom"
    assert receipt.outcomes[1].error == "aborted_by_fail_fast"


def test_item3_item4_and_item5_validation_edges() -> None:
    with pytest.raises(ValueError, match="identifiers MUST be non-empty"):
        StepFunctionOutput(step_id=" ", function_ref="fn", receipt_digest=DIGEST, values={})
    with pytest.raises(ValueError, match="receipt_digest MUST be SHA-256"):
        StepFunctionOutput(step_id="s1", function_ref="fn", receipt_digest="bad", values={})

    step_out = StepFunctionOutput(
        step_id="s1",
        function_ref="fn",
        receipt_digest=DIGEST,
        values={"tier": "low", "bad": ["not-scalar"]},  # type: ignore[dict-item]
    )
    with pytest.raises(ValueError, match="Malformed step output token"):
        resolve_step_output_params({"k": "${step.invalid}"}, {"s1": step_out})
    with pytest.raises(LookupError, match="missing or unreceipted"):
        resolve_step_output_params({"k": "${step.s2.output.tier}"}, {"s1": step_out})
    with pytest.raises(KeyError, match="absent from step"):
        resolve_step_output_params({"k": "${step.s1.output.missing}"}, {"s1": step_out})
    with pytest.raises(TypeError, match="MUST be a scalar"):
        resolve_step_output_params({"k": "${step.s1.output.bad}"}, {"s1": step_out})

    with pytest.raises(ValueError, match="non-empty outcomes"):
        evaluate_ontology_decision_branch(
            declared_outcomes=(),
            step_output=step_out,
            field_name="tier",
            value_to_outcome={"low": "go"},
        )
    with pytest.raises(KeyError, match="absent from step"):
        evaluate_ontology_decision_branch(
            declared_outcomes=("go",),
            step_output=step_out,
            field_name="missing",
            value_to_outcome={"low": "go"},
        )
    with pytest.raises(ValueError, match="does not map to a declared outcome"):
        evaluate_ontology_decision_branch(
            declared_outcomes=("go",),
            step_output=step_out,
            field_name="tier",
            value_to_outcome={"low": "undeclared"},
        )

    with pytest.raises(ValueError, match="trigger_id MUST be non-empty"):
        OntologyConditionTriggerEvaluator(trigger_id=" ")
    evaluator = OntologyConditionTriggerEvaluator(trigger_id="trig.edge")
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluator.evaluate_transition(
            member_id="svc-1",
            condition_satisfied=True,
            complete=True,
            receipt_digest=DIGEST,
            observed_at=datetime(2026, 11, 4, 12),
        )
    assert (
        evaluator.evaluate_transition(
            member_id="svc-1",
            condition_satisfied=True,
            complete=True,
            receipt_digest="invalid",
            observed_at=NOW,
        )
        is None
    )


async def test_item6_ownership_resolver_and_runtime_edges() -> None:
    from fdai.core.measurement.closed_loop_governance import WorkflowScaleSafetyController
    from fdai.core.runbook.models import RunbookStepOutcome, RunbookStepResult
    from fdai.core.workflow import OntologyAwareWorkflowRuntime
    from fdai.core.workflow.orchestrator import ProcessRun
    from fdai.rule_catalog.schema.action_type import load_action_type_catalog
    from fdai.rule_catalog.schema.workflow import load_workflow_catalog
    from fdai.shared.contracts.models import Workflow
    from fdai.shared.providers.process_runtime import ProcessStatus
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class _StubOntologyStore:
        def __init__(
            self,
            target: OntologyObjectRecord | None,
            graph: OntologyGraphSnapshot,
        ) -> None:
            self._target = target
            self._graph = graph

        async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
            return self._target if self._target and self._target.id == object_id else None

        async def traverse(self, **_: object) -> OntologyGraphSnapshot:
            return self._graph

    res_obj = OntologyObjectRecord(id="res-1", object_type="Resource", properties={"id": "res-1"})
    resolver_empty = OntologyOwnershipApprovalResolver(
        _StubOntologyStore(None, OntologyGraphSnapshot(source_complete=True))  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        await resolver_empty.resolve(target_resource_ref="res-1", at=datetime(2026, 11, 4, 12))
    assert await resolver_empty.resolve(target_resource_ref="res-1", at=NOW) is None

    incomplete_resolver = OntologyOwnershipApprovalResolver(
        _StubOntologyStore(res_obj, OntologyGraphSnapshot(source_complete=False))  # type: ignore[arg-type]
    )
    assert await incomplete_resolver.resolve(target_resource_ref="res-1", at=NOW) is None

    no_services_resolver = OntologyOwnershipApprovalResolver(
        _StubOntologyStore(
            res_obj,
            OntologyGraphSnapshot(objects=(res_obj,), links=(), source_complete=True),
        )  # type: ignore[arg-type]
    )
    assert await no_services_resolver.resolve(target_resource_ref="res-1", at=NOW) is None

    svc_active = OntologyObjectRecord(
        id="svc-active",
        object_type="BusinessService",
        properties={
            "effective_from": (NOW - timedelta(days=1)).isoformat(),
            "effective_to": "invalid-iso",
        },
    )
    svc_future = OntologyObjectRecord(
        id="svc-future",
        object_type="BusinessService",
        properties={
            "effective_from": datetime(2026, 11, 5, 12),
            "effective_to": 123,
        },
    )
    svc_not_yet = OntologyObjectRecord(
        id="svc-not-yet",
        object_type="BusinessService",
        properties={"effective_from": (NOW + timedelta(days=2)).isoformat()},
    )
    own_expired = OntologyObjectRecord(
        id="own-expired",
        object_type="Ownership",
        properties={
            "owner_ref": "team:old",
            "effective_to": (NOW - timedelta(hours=1)).isoformat(),
        },
    )
    own_blank = OntologyObjectRecord(
        id="own-blank",
        object_type="Ownership",
        properties={"owner_ref": "", "escalation_ref": ""},
    )
    links = (
        OntologyLinkRecord("workload_runs_on", "wl-1", "res-1"),
        OntologyLinkRecord("implemented_by", "svc-active", "wl-1"),
        OntologyLinkRecord("implemented_by", "svc-future", "wl-1"),
        OntologyLinkRecord("implemented_by", "svc-not-yet", "wl-1"),
        OntologyLinkRecord("implemented_by", "svc-missing", "wl-1"),
        OntologyLinkRecord("service_owned_by", "svc-active", "own-missing"),
        OntologyLinkRecord("service_owned_by", "svc-active", "own-expired"),
        OntologyLinkRecord("service_owned_by", "svc-active", "own-blank"),
    )
    blank_resolver = OntologyOwnershipApprovalResolver(
        _StubOntologyStore(
            res_obj,
            OntologyGraphSnapshot(
                objects=(res_obj, svc_active, svc_future, svc_not_yet, own_expired, own_blank),
                links=links,
                source_complete=True,
            ),
        )  # type: ignore[arg-type]
    )
    assert await blank_resolver.resolve(target_resource_ref="res-1", at=NOW) is None

    own_valid = OntologyObjectRecord(
        id="own-valid",
        object_type="Ownership",
        properties={"owner_ref": "team:sre", "escalation_ref": "oncall:sre"},
    )
    valid_resolver = OntologyOwnershipApprovalResolver(
        _StubOntologyStore(
            res_obj,
            OntologyGraphSnapshot(
                objects=(res_obj, svc_active, own_valid),
                links=(
                    *links,
                    OntologyLinkRecord("service_owned_by", "svc-active", "own-valid"),
                ),
                source_complete=True,
            ),
        )  # type: ignore[arg-type]
    )

    class _StubOrchestrator:
        def __init__(
            self, status: ProcessStatus, step_results: tuple[RunbookStepResult, ...]
        ) -> None:
            self.status = status
            self.step_results = step_results
            self.last_workflow: Workflow | None = None
            self.last_context: dict[str, str] = {}

        async def run(
            self,
            workflow: Workflow,
            *,
            target_resource_id: str,
            trigger_ts: datetime,
            context: dict[str, str],
            mode: object,
        ) -> ProcessRun:
            self.last_workflow = workflow
            self.last_context = dict(context)
            return ProcessRun(
                process_id="proc-stub-1",
                workflow_name=workflow.name,
                status=self.status,
                step_results=self.step_results,
                approval_plan=None,  # type: ignore[arg-type]
            )

    registry = PackageResourceSchemaRegistry()
    actions = {
        a.name: a
        for a in load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=registry,
            probes_root=REPO_ROOT / "rule-catalog" / "probes",
        )
    }
    base_wf = next(
        w
        for w in load_workflow_catalog(
            REPO_ROOT / "rule-catalog" / "workflows",
            schema_registry=registry,
            action_type_names=set(actions),
        )
        if w.name == "blast-radius-gated-service-restart"
    )
    wf = base_wf.model_copy(
        update={
            "steps": [
                base_wf.steps[0].model_copy(
                    update={"params": {"tier": "${step.assess.output.tier}"}}
                ),
                base_wf.steps[1].model_copy(update={"params": {}}),
            ]
        }
    )
    state_store = InMemoryStateStore()
    scale_safety = WorkflowScaleSafetyController(state_store, max_active_per_scope=1)
    await scale_safety.acquire_target_and_scope(
        scope_ref="scope-locked", target_resource_ref="res-locked", process_id="other-proc"
    )
    stub_orch = _StubOrchestrator(
        ProcessStatus.RUNNING,
        (
            RunbookStepResult(
                step_id="s1",
                action_type="ops.restart-service",
                outcome=RunbookStepOutcome.SUCCESS,
            ),
        ),
    )
    runtime_locked = OntologyAwareWorkflowRuntime(
        orchestrator=stub_orch,  # type: ignore[arg-type]
        state_store=state_store,
        ownership_resolver=valid_resolver,
        scale_safety=scale_safety,
    )
    blocked = await runtime_locked.execute(
        wf, scope_ref="scope-locked", target_resource_id="res-locked", trigger_ts=NOW
    )
    assert blocked.run is None
    assert blocked.blocked_by_scale_safety_reason is not None

    completed = await runtime_locked.execute(
        wf,
        scope_ref="scope-free",
        target_resource_id="res-1",
        trigger_ts=NOW,
        step_outputs={
            "assess": StepFunctionOutput(
                step_id="assess",
                function_ref="fn.assess",
                receipt_digest=DIGEST,
                values={"tier": "low"},
            )
        },
    )
    assert completed.run is not None
    assert completed.resolved_ownership is not None
    assert stub_orch.last_context["ontology.owner_refs"] == "team:sre"
    assert stub_orch.last_workflow is not None
    assert stub_orch.last_workflow.steps[0].params["tier"] == "low"
