"""Scenario branch and What-If digital twin simulation (Items 17-20).

Provides:
17. ``simulate_workflow_on_scenario_branch``: materializes a proposed workflow change set on a
    copy-on-write ``OntologyScenarioBranch`` and evaluates ``decision.blast_radius`` before and
    after the overlay.
18. ``compare_counterfactual_options``: runs multiple candidate ``ActionOption`` overlays on
    isolated scenario branches and ranks them by blast-radius safety and expected utility.
19. ``build_workflow_topology_preview``: summarizes added/updated/deleted ontology objects and
    links plus gate previews for the Workflow Builder UI without granting mutation authority.
20. ``validate_chaos_spof_recovery_readiness``: couples ``decision.spof_exposure`` with
    ``decision.recovery_feasibility`` so Chaos experiments target SPOF candidates only when a
    rehearsed ``RecoveryPlan`` is ready.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.operational_context.evidence_bundle_models import OperationalEvidenceBundle
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

from .advanced_decision_functions import (
    RecoveryFeasibilityEvidence,
    SpofExposureEvidence,
    assess_recovery_feasibility,
    assess_spof_exposure,
)
from .decision_evidence_readers import OntologyBlastRadiusEvidenceReader
from .decision_functions import assess_blast_radius
from .scenario_branch import (
    OntologyScenarioBranch,
    OntologyScenarioChangeSet,
    OntologyScenarioResult,
)


@dataclass(frozen=True, slots=True)
class BranchBlastRadiusSimulation:
    """Item 17: Pre-flight comparison of base vs scenario-branch blast radius."""

    branch_result: OntologyScenarioResult
    target_ref: str
    base_blast_radius: dict[str, object]
    branch_blast_radius: dict[str, object]
    score_delta: int
    gate_satisfied_after_change: bool
    execution_authority: Literal[False] = False


async def simulate_workflow_on_scenario_branch(
    *,
    branch_id: str,
    evidence_bundle: OperationalEvidenceBundle,
    base: OntologyGraphSnapshot,
    changes: OntologyScenarioChangeSet,
    object_types: tuple[OntologyObjectType, ...],
    link_types: tuple[OntologyLinkType, ...],
    target_ref: str,
    max_tier: str,
    at: datetime,
) -> BranchBlastRadiusSimulation:
    """Item 17: Apply a ChangeSet on a scenario branch and evaluate blast radius pre/post."""

    branch = OntologyScenarioBranch(
        branch_id=branch_id,
        evidence_bundle=evidence_bundle,
        base=base,
        object_types=object_types,
        link_types=link_types,
    )
    branch_res = await branch.materialize(changes)
    base_eval = await _eval_snapshot_blast(
        base, object_types, link_types, target_ref=target_ref, max_tier=max_tier, at=at
    )
    post_eval = await _eval_snapshot_blast(
        branch_res.graph,
        object_types,
        link_types,
        target_ref=target_ref,
        max_tier=max_tier,
        at=at,
    )
    base_score = _int_score(base_eval)
    post_score = _int_score(post_eval)
    return BranchBlastRadiusSimulation(
        branch_result=branch_res,
        target_ref=target_ref,
        base_blast_radius=base_eval,
        branch_blast_radius=post_eval,
        score_delta=post_score - base_score,
        gate_satisfied_after_change=bool(post_eval.get("gate_satisfied")),
    )


@dataclass(frozen=True, slots=True)
class CounterfactualOptionSpec:
    """Item 18: One candidate option and its hypothetical ontology overlay."""

    option_id: str
    branch_id: str
    expected_utility: float
    changes: OntologyScenarioChangeSet


@dataclass(frozen=True, slots=True)
class CounterfactualOptionOutcome:
    """Item 18: Simulated outcome for one counterfactual option."""

    option_id: str
    branch_id: str
    scenario_digest: str
    expected_utility: float
    post_blast_score: int
    post_blast_tier: str
    gate_satisfied: bool


@dataclass(frozen=True, slots=True)
class CounterfactualComparisonReport:
    """Item 18: Ranked counterfactual options across isolated scenario branches."""

    target_ref: str
    ranked_outcomes: tuple[CounterfactualOptionOutcome, ...]
    recommended_option_id: str | None
    comparison_digest: str
    execution_authority: Literal[False] = False


async def compare_counterfactual_options(
    *,
    evidence_bundle: OperationalEvidenceBundle,
    base: OntologyGraphSnapshot,
    options: Sequence[CounterfactualOptionSpec],
    object_types: tuple[OntologyObjectType, ...],
    link_types: tuple[OntologyLinkType, ...],
    target_ref: str,
    max_tier: str,
    at: datetime,
) -> CounterfactualComparisonReport:
    """Item 18: Simulate each option on an isolated branch and rank gate-safe options first."""

    if not options or len({opt.option_id for opt in options}) != len(options):
        raise ValueError("counterfactual options MUST be non-empty and unique")
    outcomes: list[CounterfactualOptionOutcome] = []
    for opt in options:
        sim = await simulate_workflow_on_scenario_branch(
            branch_id=opt.branch_id,
            evidence_bundle=evidence_bundle,
            base=base,
            changes=opt.changes,
            object_types=object_types,
            link_types=link_types,
            target_ref=target_ref,
            max_tier=max_tier,
            at=at,
        )
        outcomes.append(
            CounterfactualOptionOutcome(
                option_id=opt.option_id,
                branch_id=opt.branch_id,
                scenario_digest=sim.branch_result.scenario_digest,
                expected_utility=opt.expected_utility,
                post_blast_score=_int_score(sim.branch_blast_radius),
                post_blast_tier=str(sim.branch_blast_radius.get("tier") or "unknown"),
                gate_satisfied=sim.gate_satisfied_after_change,
            )
        )
    ranked = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                0 if item.gate_satisfied else 1,
                item.post_blast_score,
                -item.expected_utility,
                item.option_id,
            ),
        )
    )
    recommended = next((item.option_id for item in ranked if item.gate_satisfied), None)
    digest = content_digest(
        {
            "target_ref": target_ref,
            "recommended_option_id": recommended,
            "ranked": [
                {
                    "option_id": o.option_id,
                    "scenario_digest": o.scenario_digest,
                    "post_blast_score": o.post_blast_score,
                    "gate_satisfied": o.gate_satisfied,
                }
                for o in ranked
            ],
        }
    )
    return CounterfactualComparisonReport(
        target_ref=target_ref,
        ranked_outcomes=ranked,
        recommended_option_id=recommended,
        comparison_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class WorkflowTopologyPreview:
    """Item 19: Read-only topology diff and gate preview for the Workflow Builder."""

    branch_id: str
    target_ref: str
    added_object_ids: tuple[str, ...]
    updated_object_ids: tuple[str, ...]
    deleted_object_ids: tuple[str, ...]
    added_link_count: int
    deleted_link_count: int
    gate_satisfied_before: bool
    gate_satisfied_after: bool
    preview_digest: str
    read_only: Literal[True] = True
    execution_authority: Literal[False] = False


async def build_workflow_topology_preview(
    *,
    branch_id: str,
    evidence_bundle: OperationalEvidenceBundle,
    base: OntologyGraphSnapshot,
    changes: OntologyScenarioChangeSet,
    object_types: tuple[OntologyObjectType, ...],
    link_types: tuple[OntologyLinkType, ...],
    target_ref: str,
    max_tier: str,
    at: datetime,
) -> WorkflowTopologyPreview:
    """Item 19: Build a read-only topology diff and gate preview from a scenario simulation."""

    sim = await simulate_workflow_on_scenario_branch(
        branch_id=branch_id,
        evidence_bundle=evidence_bundle,
        base=base,
        changes=changes,
        object_types=object_types,
        link_types=link_types,
        target_ref=target_ref,
        max_tier=max_tier,
        at=at,
    )
    base_ids = {obj.id for obj in base.objects}
    upsert_ids = {obj.id for obj in changes.upsert_objects}
    added = tuple(sorted(upsert_ids - base_ids))
    updated = tuple(sorted(upsert_ids & base_ids))
    deleted = tuple(sorted(set(changes.delete_object_ids) & base_ids))
    before_ok = bool(sim.base_blast_radius.get("gate_satisfied"))
    after_ok = sim.gate_satisfied_after_change
    digest = content_digest(
        {
            "scenario_digest": sim.branch_result.scenario_digest,
            "target_ref": target_ref,
            "added": list(added),
            "updated": list(updated),
            "deleted": list(deleted),
            "before_ok": before_ok,
            "after_ok": after_ok,
        }
    )
    return WorkflowTopologyPreview(
        branch_id=branch_id,
        target_ref=target_ref,
        added_object_ids=added,
        updated_object_ids=updated,
        deleted_object_ids=deleted,
        added_link_count=len(changes.upsert_links),
        deleted_link_count=len(changes.delete_link_keys),
        gate_satisfied_before=before_ok,
        gate_satisfied_after=after_ok,
        preview_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class ChaosSpofValidationReceipt:
    """Item 20: Pre-flight validation coupling SPOF exposure with RecoveryPlan readiness."""

    target_ref: str
    spof_tier: str
    is_spof_candidate: bool
    recovery_feasible: bool
    chaos_drill_admitted: bool
    reason_code: str
    receipt_digest: str
    execution_authority: Literal[False] = False


def validate_chaos_spof_recovery_readiness(
    *,
    target_ref: str,
    spof_evidence: SpofExposureEvidence,
    recovery_evidence: RecoveryFeasibilityEvidence,
) -> ChaosSpofValidationReceipt:
    """Item 20: Admit a Chaos resilience drill on a SPOF candidate only when recovery is ready."""

    spof = assess_spof_exposure(spof_evidence, target_ref=target_ref, max_tier="none")
    recovery = assess_recovery_feasibility(recovery_evidence, target_ref=target_ref)
    spof_tier = str(spof["tier"])
    is_candidate = bool(spof["complete"]) and spof_tier in {"medium", "high", "critical"}
    rec_ok = bool(recovery["gate_satisfied"])
    if not spof["complete"] or not recovery["complete"]:
        admitted = False
        reason = "evidence_incomplete"
    elif not is_candidate:
        admitted = False
        reason = "not_a_spof_candidate"
    elif not rec_ok:
        admitted = False
        reason = "recovery_plan_not_feasible"
    else:
        admitted = True
        reason = "spof_candidate_with_verified_recovery"
    digest = content_digest(
        {
            "target_ref": target_ref,
            "spof_tier": spof_tier,
            "is_spof_candidate": is_candidate,
            "recovery_feasible": rec_ok,
            "chaos_drill_admitted": admitted,
            "reason_code": reason,
        }
    )
    return ChaosSpofValidationReceipt(
        target_ref=target_ref,
        spof_tier=spof_tier,
        is_spof_candidate=is_candidate,
        recovery_feasible=rec_ok,
        chaos_drill_admitted=admitted,
        reason_code=reason,
        receipt_digest=digest,
    )


def _int_score(reading: dict[str, object]) -> int:
    val = reading.get("score")
    return val if isinstance(val, int) and not isinstance(val, bool) else 0


async def _eval_snapshot_blast(
    snapshot: OntologyGraphSnapshot,
    object_types: tuple[OntologyObjectType, ...],
    link_types: tuple[OntologyLinkType, ...],
    *,
    target_ref: str,
    max_tier: str,
    at: datetime,
) -> dict[str, object]:
    store = InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=link_types,
        source_complete=snapshot.source_complete,
        source_generation=snapshot.source_generation or "scenario-branch",
    )
    for obj in snapshot.objects:
        await store.upsert_object(obj)
    for lnk in snapshot.links:
        await store.upsert_link(lnk)
    reader = OntologyBlastRadiusEvidenceReader(store, clock=lambda: at)
    ev = await reader.read(target_ref=target_ref)
    if ev is None:
        return {"tier": "unknown", "score": 0, "complete": False, "gate_satisfied": False}
    return assess_blast_radius(ev, target_ref=target_ref, max_tier=max_tier)


__all__ = [
    "BranchBlastRadiusSimulation",
    "ChaosSpofValidationReceipt",
    "CounterfactualComparisonReport",
    "CounterfactualOptionOutcome",
    "CounterfactualOptionSpec",
    "WorkflowTopologyPreview",
    "build_workflow_topology_preview",
    "compare_counterfactual_options",
    "simulate_workflow_on_scenario_branch",
    "validate_chaos_spof_recovery_readiness",
]
