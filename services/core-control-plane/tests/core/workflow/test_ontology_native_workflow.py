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
