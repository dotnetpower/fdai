"""Tests for Area E (Items 21-25): AIP agent tools, workflow compiler, RCA filter, and briefing."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fdai.core.ontology_platform.aip_agent_integration import (
    OntologyDecisionToolAdapter,
    WorkflowIntentSpec,
    build_approver_decision_briefing,
    compile_intent_to_shadow_workflow,
    plan_evidence_recovery_on_abstention,
    select_graded_hypotheses_for_incident_rca,
)
from fdai.core.ontology_platform.decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    CHANGE_RISK_FUNCTION_NAME,
    COST_OF_DELAY_FUNCTION_NAME,
    BlastRadiusEvidence,
    CostOfDelayEvidence,
    ImpactedResource,
    assess_cost_of_delay,
    blast_radius_function,
    blast_radius_function_type,
    decision_function_types,
)
from fdai.core.ontology_platform.functions import OntologyFunctionRegistry
from fdai.core.ontology_platform.workflow_gate_reader import GateTargetAnchorResolver
from fdai.delivery.azure.catalog_causal_prediction_engine import (
    load_causal_prediction_scenario_catalog,
)
from fdai.runtime.causal_bindings import build_catalog_causal_grade_bridge
from fdai.shared.contracts.models import Mode, WorkflowStepKind
from fdai.shared.ontology.release import build_ontology_release

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


class _BlastStub:
    async def read(self, *, target_ref: str) -> BlastRadiusEvidence:
        return BlastRadiusEvidence(
            resources=(ImpactedResource(target_ref, 0, "low"),),
            traversal_complete=True,
            source_generation="gen-1",
            observed_at=NOW,
        )


async def test_item21_t2_decision_tool_adapter_invokes_allowlisted_function_with_receipt() -> None:
    decls = decision_function_types()
    release = build_ontology_release(function_types=decls)
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        blast_radius_function_type(),
        blast_radius_function(reader=_BlastStub(), anchor_resolver=GateTargetAnchorResolver()),
    )
    adapter = OntologyDecisionToolAdapter(registry)

    receipt = await adapter.invoke_decision_tool(
        caller_agent="Mimir",
        function_name=BLAST_RADIUS_FUNCTION_NAME,
        target_ref="res-1",
        arguments={"max_tier": "medium"},
    )
    assert receipt.execution_authority is False
    assert receipt.output["tier"] == "low"
    assert receipt.invocation_receipt.output_digest.startswith("sha256:")

    with pytest.raises(PermissionError, match="not an allowlisted"):
        await adapter.invoke_decision_tool(
            caller_agent="Mimir",
            function_name="query.inventory_impact",
            target_ref="res-1",
            arguments={},
        )


def test_item22_compile_intent_to_shadow_workflow_enforces_gates_and_shadow_mode() -> None:
    intent = WorkflowIntentSpec(
        name="safe-friday-gpu-stop",
        description="Stop idle non-prod GPU VMs when blast radius and change risk are low.",
        signal_type="change.request.submitted",
        ontology_gate_functions=(BLAST_RADIUS_FUNCTION_NAME, CHANGE_RISK_FUNCTION_NAME),
        approval_role="owner",
        approval_quorum=2,
        action_type_ref="ops.deallocate-vm",
        compensated_by="ops.start-vm",
        action_params={"reason": "${change.reason}"},
    )
    wf = compile_intent_to_shadow_workflow(
        intent,
        registered_action_types=frozenset({"ops.deallocate-vm", "ops.start-vm"}),
    )
    assert wf.default_mode is Mode.SHADOW
    assert len(wf.steps) == 4
    assert wf.steps[0].kind is WorkflowStepKind.GATE
    assert wf.steps[0].gate_ref == "ontology-function:decision.blast_radius"
    assert wf.steps[1].gate_ref == "ontology-function:decision.change_risk"
    assert wf.steps[2].kind is WorkflowStepKind.APPROVAL
    assert wf.steps[3].action_type_ref == "ops.deallocate-vm"

    # Rejects ungated ranking signal as a boolean workflow gate
    bad_intent = WorkflowIntentSpec(
        name="bad-cost-gate",
        description="Invalid cost gate",
        signal_type="change.request.submitted",
        ontology_gate_functions=(COST_OF_DELAY_FUNCTION_NAME,),
        approval_role="owner",
        approval_quorum=1,
        action_type_ref="ops.deallocate-vm",
    )
    with pytest.raises(ValueError, match="cannot be used as a boolean workflow gate"):
        compile_intent_to_shadow_workflow(
            bad_intent, registered_action_types=frozenset({"ops.deallocate-vm"})
        )


def test_items_23_24_25_incident_rca_selection_abstention_recovery_and_approver_briefing() -> None:
    bridge = build_catalog_causal_grade_bridge(repo_root=REPO_ROOT)
    spec = load_causal_prediction_scenario_catalog(REPO_ROOT).get_by_round("D001")
    supported_run = bridge.execute_and_grade_scenario(spec, base_time=NOW)
    reviewed = bridge.resolve_mechanism(spec.causal_mechanisms[0])
    withheld_run = bridge.execute_and_grade_scenario(
        spec,
        base_time=NOW,
        missing_refutation_reads=(reviewed.refutation_reads[0],),
        refutation_reads_run=(reviewed.refutation_reads[1],),
    )
    hyp_ok = supported_run.report.causal_result.hypothesis_record
    hyp_withheld = withheld_run.report.causal_result.hypothesis_record

    selection = select_graded_hypotheses_for_incident_rca(
        incident_id=hyp_ok.incident_id,
        candidates=(
            (hyp_ok, supported_run.grade_receipt),
            (hyp_withheld, withheld_run.grade_receipt),
        ),
    )
    assert len(selection.admitted_hypotheses) == 1
    assert len(selection.withheld_hypothesis_ids) == 1

    recovery_plan = plan_evidence_recovery_on_abstention(
        target_ref="res-1",
        decision_reason_codes=("criticality_unreviewed", "change_window_unobserved"),
        missing_refutation_reads=withheld_run.grade_receipt.missing_refutation_reads,
    )
    assert recovery_plan is not None
    assert recovery_plan.action_type_ref == "tool.run-investigation"
    assert "probe.service_catalog_criticality_sync" in recovery_plan.required_probes

    cost_signal = assess_cost_of_delay(
        CostOfDelayEvidence(Decimal("45"), "USD", "basis:1", NOW),
        target_ref="res-1",
        delay_hours=4,
    )
    briefing = build_approver_decision_briefing(
        process_id="proc-1",
        workflow_name="change-risk-gated-scale-in",
        target_resource_ref="res-1",
        recommended_action_type="ops.scale-in",
        compensated_by="ops.scale-out",
        blast_radius_reading={"tier": "low", "complete": True},
        change_risk_reading={"tier": "low", "complete": True},
        impacted_service_refs=("svc-checkout",),
        rca_selection=selection,
        cost_of_delay_reading=cost_signal,
        evidence_refs=("evidence:1",),
        generated_at=NOW,
    )
    assert briefing.read_only is True
    assert briefing.execution_authority is False
    assert briefing.cost_of_delay_amount == Decimal("180")
    assert briefing.supported_hypothesis_id == hyp_ok.hypothesis_id
    assert briefing.refuted_or_withheld_count == 1
    assert briefing.briefing_digest.startswith("sha256:")
