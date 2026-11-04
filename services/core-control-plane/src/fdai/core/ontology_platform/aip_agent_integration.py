"""T2 agent ontology decision tools, workflow compiler, RCA filter, and briefing (Items 21-25).

Provides:
21. ``OntologyDecisionToolAdapter``: allowlisted tool adapter letting T2 reasoning invoke
    deterministic ``decision.*`` functions through ``OntologyFunctionRegistry`` with receipts.
22. ``compile_intent_to_shadow_workflow``: compiles structured operational intent into a
    schema-valid, shadow-mode ``Workflow`` definition bound to ontology function gates.
23. ``select_graded_hypotheses_for_incident_rca``: filters candidate causal inference results
    through ``CausalGradeReceipt`` refutation accounting for live Incident RCA.
24. ``plan_evidence_recovery_on_abstention``: maps ``reason_codes`` and missing refutation reads
    into a read-only ``tool.run-investigation`` recovery plan when a gate or RCA abstains.
25. ``build_approver_decision_briefing``: assembles a digest-bound briefing package for human
    approvers summarizing gate readings, impacted services, causal grade, cost of delay, and
    rollback plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.conversation.causal_grade_receipts import (
    CausalGradeReceipt,
    supports_causal_hypothesis,
)
from fdai.core.rca.hypothesis import CausalHypothesisRecord
from fdai.shared.contracts.models import (
    CeilingRole,
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowStepKind,
    WorkflowTrigger,
    WorkflowTriggerKind,
)

from .advanced_decision_functions import (
    CHANGE_COLLISION_FUNCTION_NAME,
    RECOVERY_FEASIBILITY_FUNCTION_NAME,
    SLO_EXHAUSTION_ETA_FUNCTION_NAME,
    SPOF_EXPOSURE_FUNCTION_NAME,
)
from .decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    CHANGE_RISK_FUNCTION_NAME,
    COST_OF_DELAY_FUNCTION_NAME,
    DECISION_PURPOSE,
)
from .finops_value_modeling import BUDGET_BURN_RISK_FUNCTION_NAME
from .functions import (
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunctionRegistry,
)
from .workflow_gate_reader import GATE_TARGET_EVIDENCE_PREFIX

ALLOWED_DECISION_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        BLAST_RADIUS_FUNCTION_NAME,
        CHANGE_RISK_FUNCTION_NAME,
        COST_OF_DELAY_FUNCTION_NAME,
        SLO_EXHAUSTION_ETA_FUNCTION_NAME,
        CHANGE_COLLISION_FUNCTION_NAME,
        RECOVERY_FEASIBILITY_FUNCTION_NAME,
        SPOF_EXPOSURE_FUNCTION_NAME,
        BUDGET_BURN_RISK_FUNCTION_NAME,
    }
)

_REASON_TO_PROBE: Final[Mapping[str, str]] = {
    "criticality_unreviewed": "probe.service_catalog_criticality_sync",
    "traversal_incomplete": "probe.inventory_dependency_refresh",
    "blast_radius_unobserved": "probe.inventory_dependency_refresh",
    "change_window_unobserved": "probe.change_window_schedule_read",
    "recent_failed_changes_unobserved": "probe.arg_resource_changes_poll",
    "rollback_tested_unobserved": "probe.recovery_plan_rehearsal_check",
    "dry_run_unobserved": "probe.shadow_action_run_history_read",
    "hourly_cost_unobserved": "probe.cost_observation_collect",
    "currency_unobserved": "probe.cost_observation_collect",
    "remaining_budget_unobserved": "probe.slo_burn_rate_window_read",
    "burn_rate_unobserved": "probe.slo_burn_rate_window_read",
    "subgraph_incomplete": "probe.inventory_dependency_refresh",
}


@dataclass(frozen=True, slots=True)
class GroundedDecisionToolCallReceipt:
    """Item 21: Receipted result of a T2 agent tool call to a ``decision.*`` function."""

    function_name: str
    target_ref: str
    output: Mapping[str, Any]
    invocation_receipt: FunctionInvocationReceipt
    execution_authority: Literal[False] = False


class OntologyDecisionToolAdapter:
    """Item 21: Allowlisted read-only tool adapter over OntologyFunctionRegistry for T2 agents."""

    def __init__(self, registry: OntologyFunctionRegistry) -> None:
        self._registry = registry

    async def invoke_decision_tool(
        self,
        *,
        caller_agent: str,
        function_name: str,
        target_ref: str,
        arguments: Mapping[str, Any],
    ) -> GroundedDecisionToolCallReceipt:
        if function_name not in ALLOWED_DECISION_TOOL_NAMES:
            raise PermissionError(f"Function {function_name!r} is not an allowlisted decision tool")
        if not target_ref.strip():
            raise ValueError("target_ref MUST be non-empty")
        ctx = FunctionInvocationContext(
            caller_agent=caller_agent,
            caller_role=CeilingRole.READER,
            purposes=(DECISION_PURPOSE,),
            evidence_refs=(f"{GATE_TARGET_EVIDENCE_PREFIX}{target_ref}",),
        )
        result, receipt = await self._registry.invoke_with_receipt(
            function_name, arguments, context=ctx
        )
        if not isinstance(result, Mapping):
            raise TypeError("decision tool output MUST be a mapping")
        return GroundedDecisionToolCallReceipt(
            function_name=function_name,
            target_ref=target_ref,
            output=dict(result),
            invocation_receipt=receipt,
        )


@dataclass(frozen=True, slots=True)
class WorkflowIntentSpec:
    """Item 22: Structured operational intent to compile into a shadow Workflow."""

    name: str
    description: str
    signal_type: str
    ontology_gate_functions: tuple[str, ...]
    approval_role: str
    approval_quorum: int
    action_type_ref: str
    compensated_by: str | None = None
    action_params: Mapping[str, str | int | float | bool] | None = None


def compile_intent_to_shadow_workflow(
    intent: WorkflowIntentSpec,
    *,
    registered_action_types: frozenset[str],
) -> Workflow:
    """Item 22: Compile a structured operational intent into a schema-valid shadow Workflow."""

    if intent.action_type_ref not in registered_action_types:
        raise ValueError(f"Unknown action_type_ref: {intent.action_type_ref!r}")
    if intent.compensated_by is not None and intent.compensated_by not in registered_action_types:
        raise ValueError(f"Unknown compensated_by ActionType: {intent.compensated_by!r}")
    if not intent.ontology_gate_functions:
        raise ValueError("Compiled workflow intent MUST include at least one ontology gate")
    for fn_name in intent.ontology_gate_functions:
        if fn_name not in ALLOWED_DECISION_TOOL_NAMES or fn_name == COST_OF_DELAY_FUNCTION_NAME:
            raise ValueError(f"Function {fn_name!r} cannot be used as a boolean workflow gate")
    steps: list[WorkflowStep] = []
    for idx, fn_name in enumerate(intent.ontology_gate_functions, start=1):
        steps.append(
            WorkflowStep(
                id=f"gate_{idx}_{fn_name.replace('.', '_')}",
                kind=WorkflowStepKind.GATE,
                gate_ref=f"ontology-function:{fn_name}",
            )
        )
    steps.append(
        WorkflowStep(
            id="human_approval",
            kind=WorkflowStepKind.APPROVAL,
            approval_role=intent.approval_role,  # type: ignore[arg-type]
            quorum=intent.approval_quorum,
            no_self_approval=True,
            timeout_seconds=3600,
        )
    )
    steps.append(
        WorkflowStep(
            id="execute_action",
            kind=WorkflowStepKind.ACTION,
            action_type_ref=intent.action_type_ref,
            compensated_by=intent.compensated_by,
            params=dict(intent.action_params or {}),
        )
    )
    return Workflow(
        schema_version="1.0.0",
        name=intent.name,
        version="1.0.0",
        description=intent.description,
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type=intent.signal_type,
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=21,
            min_samples=40,
            min_accuracy=0.98,
            max_policy_escapes=0,
        ),
        steps=steps,
        anti_scope="Shadow-only compiled workflow; never grants standing execution authority.",
    )


@dataclass(frozen=True, slots=True)
class IncidentRcaHypothesisSelection:
    """Item 23: Admitted vs withheld causal hypotheses for live Incident RCA."""

    incident_id: str
    admitted_hypotheses: tuple[CausalHypothesisRecord, ...]
    withheld_hypothesis_ids: tuple[str, ...]
    receipt_digests: tuple[str, ...]
    selection_digest: str


def select_graded_hypotheses_for_incident_rca(
    *,
    incident_id: str,
    candidates: Sequence[tuple[CausalHypothesisRecord, CausalGradeReceipt]],
) -> IncidentRcaHypothesisSelection:
    """Item 23: Admit only hypotheses whose E8 CausalGradeReceipt reaches predictive_precedence."""

    if not incident_id.strip():
        raise ValueError("incident_id MUST be non-empty")
    admitted: list[CausalHypothesisRecord] = []
    withheld: list[str] = []
    digests: list[str] = []
    for hyp, receipt in candidates:
        if hyp.incident_id != incident_id:
            raise ValueError("Candidate hypothesis incident_id mismatch")
        digests.append(receipt.receipt_digest)
        if supports_causal_hypothesis(receipt):
            admitted.append(hyp)
        else:
            withheld.append(hyp.hypothesis_id)
    ordered_admitted = tuple(
        sorted(admitted, key=lambda h: (-h.confidence, h.ambiguity, h.hypothesis_id))
    )
    ordered_withheld = tuple(sorted(withheld))
    ordered_digests = tuple(sorted(set(digests)))
    sel_digest = content_digest(
        {
            "incident_id": incident_id,
            "admitted": [h.hypothesis_id for h in ordered_admitted],
            "withheld": list(ordered_withheld),
            "receipt_digests": list(ordered_digests),
        }
    )
    return IncidentRcaHypothesisSelection(
        incident_id=incident_id,
        admitted_hypotheses=ordered_admitted,
        withheld_hypothesis_ids=ordered_withheld,
        receipt_digests=ordered_digests,
        selection_digest=sel_digest,
    )


@dataclass(frozen=True, slots=True)
class AbstentionRecoveryPlan:
    """Item 24: Read-only evidence collection plan triggered when a gate or RCA abstains."""

    target_ref: str
    action_type_ref: Literal["tool.run-investigation"]
    required_probes: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]
    plan_digest: str
    execution_authority: Literal[False] = False


def plan_evidence_recovery_on_abstention(
    *,
    target_ref: str,
    decision_reason_codes: Sequence[str] = (),
    missing_refutation_reads: Sequence[str] = (),
) -> AbstentionRecoveryPlan | None:
    """Item 24: Map missing evidence reasons into a bounded read-only investigation plan."""

    if not target_ref.strip():
        raise ValueError("target_ref MUST be non-empty")
    reasons = tuple(sorted({*decision_reason_codes, *missing_refutation_reads}))
    if not reasons:
        return None
    probes: list[str] = []
    for code in decision_reason_codes:
        probes.append(_REASON_TO_PROBE.get(code, f"probe.collect_{code}"))
    for ref_read in missing_refutation_reads:
        probes.append(f"probe.refutation_{ref_read}")
    unique_probes = tuple(sorted(set(probes)))
    digest = content_digest(
        {
            "target_ref": target_ref,
            "action_type_ref": "tool.run-investigation",
            "required_probes": list(unique_probes),
            "unresolved_reasons": list(reasons),
        }
    )
    return AbstentionRecoveryPlan(
        target_ref=target_ref,
        action_type_ref="tool.run-investigation",
        required_probes=unique_probes,
        unresolved_reasons=reasons,
        plan_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class ApproverDecisionBriefing:
    """Item 25: Digest-bound briefing package presented to a human approver."""

    process_id: str
    workflow_name: str
    target_resource_ref: str
    recommended_action_type: str
    compensated_by: str | None
    blast_radius_tier: str
    change_risk_tier: str
    impacted_service_refs: tuple[str, ...]
    supported_hypothesis_id: str | None
    refuted_or_withheld_count: int
    cost_of_delay_amount: Decimal | None
    cost_of_delay_currency: str | None
    evidence_refs: tuple[str, ...]
    briefing_digest: str
    generated_at: datetime
    read_only: Literal[True] = True
    execution_authority: Literal[False] = False


def build_approver_decision_briefing(
    *,
    process_id: str,
    workflow_name: str,
    target_resource_ref: str,
    recommended_action_type: str,
    compensated_by: str | None,
    blast_radius_reading: Mapping[str, Any],
    change_risk_reading: Mapping[str, Any],
    impacted_service_refs: Sequence[str],
    rca_selection: IncidentRcaHypothesisSelection | None,
    cost_of_delay_reading: Mapping[str, Any] | None,
    evidence_refs: Sequence[str],
    generated_at: datetime,
) -> ApproverDecisionBriefing:
    """Item 25: Synthesize a verifiable approver briefing from ontology readings and RCA."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at MUST be timezone-aware")
    blast_tier = str(blast_radius_reading.get("tier") or "unknown")
    risk_tier = str(change_risk_reading.get("tier") or "unknown")
    services = tuple(sorted(set(impacted_service_refs)))
    top_hyp = (
        rca_selection.admitted_hypotheses[0].hypothesis_id
        if rca_selection and rca_selection.admitted_hypotheses
        else None
    )
    withheld_count = len(rca_selection.withheld_hypothesis_ids) if rca_selection else 0
    amount: Decimal | None = None
    currency: str | None = None
    if cost_of_delay_reading is not None and cost_of_delay_reading.get("complete") is True:
        raw_amt = cost_of_delay_reading.get("total_amount")
        raw_cur = cost_of_delay_reading.get("currency")
        if isinstance(raw_amt, str) and isinstance(raw_cur, str):
            amount = Decimal(raw_amt)
            currency = raw_cur
    refs = tuple(sorted(set(evidence_refs)))
    if not refs:
        raise ValueError("ApproverDecisionBriefing requires at least one evidence_ref")
    digest = content_digest(
        {
            "process_id": process_id,
            "workflow_name": workflow_name,
            "target_resource_ref": target_resource_ref,
            "recommended_action_type": recommended_action_type,
            "compensated_by": compensated_by,
            "blast_radius_tier": blast_tier,
            "change_risk_tier": risk_tier,
            "impacted_service_refs": list(services),
            "supported_hypothesis_id": top_hyp,
            "withheld_count": withheld_count,
            "cost_of_delay_amount": None if amount is None else str(amount),
            "cost_of_delay_currency": currency,
            "evidence_refs": list(refs),
        }
    )
    return ApproverDecisionBriefing(
        process_id=process_id,
        workflow_name=workflow_name,
        target_resource_ref=target_resource_ref,
        recommended_action_type=recommended_action_type,
        compensated_by=compensated_by,
        blast_radius_tier=blast_tier,
        change_risk_tier=risk_tier,
        impacted_service_refs=services,
        supported_hypothesis_id=top_hyp,
        refuted_or_withheld_count=withheld_count,
        cost_of_delay_amount=amount,
        cost_of_delay_currency=currency,
        evidence_refs=refs,
        briefing_digest=digest,
        generated_at=generated_at,
    )


__all__ = [
    "ALLOWED_DECISION_TOOL_NAMES",
    "AbstentionRecoveryPlan",
    "ApproverDecisionBriefing",
    "GroundedDecisionToolCallReceipt",
    "IncidentRcaHypothesisSelection",
    "OntologyDecisionToolAdapter",
    "WorkflowIntentSpec",
    "build_approver_decision_briefing",
    "compile_intent_to_shadow_workflow",
    "plan_evidence_recovery_on_abstention",
    "select_graded_hypotheses_for_incident_rca",
]
