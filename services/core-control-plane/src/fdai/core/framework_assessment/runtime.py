"""Deterministic no-authority runtime for WAF and CAF assessment."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Protocol

from fdai_service_contracts.framework_assessment import FRAMEWORK_ASSESSMENT_TOPIC

from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkControlSpecification,
    FrameworkEvidenceRole,
    FrameworkEvidenceSpecification,
    FrameworkGenerationContract,
    FrameworkRelationshipState,
    FrameworkRequirementKind,
    canonical_digest,
)

from .models import (
    FrameworkApplicabilityDecision,
    FrameworkApplicabilityStatus,
    FrameworkAssessmentRequest,
    FrameworkAssessmentResult,
    FrameworkControlResult,
    FrameworkEvaluationStatus,
    FrameworkEvidenceReceipt,
    FrameworkRequirementResult,
    FrameworkSatisfactionStatus,
)


class FrameworkAssessmentAuditStore(Protocol):
    async def append_audit_entry(self, entry: Mapping[str, object]) -> None: ...


class FrameworkAssessmentPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class FrameworkAssessmentRuntime:
    """Evaluate one complete framework profile without I/O or execution authority."""

    def __init__(self, catalog: FrameworkAssessmentCatalog) -> None:
        self._catalog = catalog

    def assess(self, request: FrameworkAssessmentRequest) -> FrameworkAssessmentResult:
        profile = request.profile
        if (
            profile.framework_id != self._catalog.framework_id
            or profile.framework_version != self._catalog.framework_version
            or profile.catalog_digest != self._catalog.catalog_digest
            or profile.scope_kind is not self._catalog.framework_scope
        ):
            raise ValueError("framework assessment profile pins do not match the catalog")
        expected_ids = tuple(item.control_id for item in self._catalog.controls)
        if tuple(item.control_id for item in profile.applicability) != expected_ids:
            raise ValueError("framework assessment profile does not cover the complete catalog")
        decisions = {item.control_id: item for item in profile.applicability}
        owners = {item.control_id: item for item in profile.owners}
        requirement_ids = {
            item.control_id: {requirement.requirement_id for requirement in item.evidence}
            for item in self._catalog.controls
        }
        evidence_by_control: dict[str, list[FrameworkEvidenceReceipt]] = {}
        for receipt in request.evidence:
            if receipt.control_id not in requirement_ids:
                raise ValueError("framework evidence references an unknown control")
            if (
                receipt.evidence_role is FrameworkEvidenceRole.DECISIVE
                and receipt.requirement_id not in requirement_ids[receipt.control_id]
            ):
                raise ValueError("framework evidence references an unknown requirement")
            evidence_by_control.setdefault(receipt.control_id, []).append(receipt)

        controls = tuple(
            self._evaluate_control(
                specification,
                request,
                decisions[specification.control_id],
                owners[specification.control_id].owner_slot,
                tuple(evidence_by_control.get(specification.control_id, ())),
            )
            for specification in self._catalog.controls
        )
        self._validate_tradeoffs(request, expected_ids)
        counts: dict[str, int] = {}
        for control in controls:
            for axis, value in (
                ("reference", control.reference_state),
                ("mapping", control.mapping_state),
                ("applicability", control.applicability.value),
                ("evaluation", control.evaluation.value),
                ("satisfaction", control.satisfaction.value),
            ):
                key = f"{axis}.{value}"
                counts[key] = counts.get(key, 0) + 1
        material = {
            "assessment_id": request.assessment_id,
            "mode": "shadow",
            "execution_authority": False,
            "framework_id": self._catalog.framework_id,
            "framework_version": self._catalog.framework_version,
            "catalog_digest": self._catalog.catalog_digest,
            "profile_id": profile.profile_id,
            "profile_digest": profile.profile_digest,
            "profile_reviewed_by": profile.reviewed_by,
            "profile_reviewed_at": profile.reviewed_at,
            "applicability_profile": profile.applicability,
            "ontology_release": profile.ontology_release,
            "scope_digest": profile.scope_digest,
            "inventory_generation": profile.inventory_generation,
            "hierarchy_generation": profile.hierarchy_generation,
            "evaluated_at": request.evaluated_at,
            "recorded_at": request.recorded_at,
            "controls": controls,
            "tradeoffs": request.tradeoffs,
            "aggregate_counts": counts,
        }
        digest_material = {
            **material,
            "evaluated_at": request.evaluated_at.isoformat(),
            "recorded_at": request.recorded_at.isoformat(),
            "profile_reviewed_at": profile.reviewed_at.isoformat(),
            "applicability_profile": [item.to_dict() for item in profile.applicability],
            "controls": [item.to_dict() for item in controls],
            "tradeoffs": [item.to_dict() for item in request.tradeoffs],
            "aggregate_counts": dict(sorted(counts.items())),
        }
        return FrameworkAssessmentResult(
            assessment_id=request.assessment_id,
            mode="shadow",
            execution_authority=False,
            framework_id=self._catalog.framework_id,
            framework_version=self._catalog.framework_version,
            catalog_digest=self._catalog.catalog_digest,
            profile_id=profile.profile_id,
            profile_digest=profile.profile_digest,
            profile_reviewed_by=profile.reviewed_by,
            profile_reviewed_at=profile.reviewed_at,
            applicability_profile=profile.applicability,
            ontology_release=profile.ontology_release,
            scope_digest=profile.scope_digest,
            inventory_generation=profile.inventory_generation,
            hierarchy_generation=profile.hierarchy_generation,
            evaluated_at=request.evaluated_at,
            recorded_at=request.recorded_at,
            controls=controls,
            tradeoffs=request.tradeoffs,
            aggregate_counts=counts,
            result_digest=canonical_digest(digest_material),
        )

    def _evaluate_control(
        self,
        specification: FrameworkControlSpecification,
        request: FrameworkAssessmentRequest,
        decision: FrameworkApplicabilityDecision,
        owner_slot: str,
        evidence: tuple[FrameworkEvidenceReceipt, ...],
    ) -> FrameworkControlResult:
        if (
            decision.owner_slot != specification.owner_slot
            or owner_slot != specification.owner_slot
        ):
            raise ValueError(
                "framework profile owner does not match reviewed evidence specification"
            )
        mapping_state = _mapping_state(specification)
        if decision.status is FrameworkApplicabilityStatus.NOT_APPLICABLE:
            if (
                decision.expires_at is None
                or decision.approved_at is None
                or decision.expires_at <= request.evaluated_at
                or decision.approved_at > request.evaluated_at
            ):
                return _control_result(
                    specification,
                    decision.status,
                    mapping_state,
                    FrameworkEvaluationStatus.NOT_EVALUATED,
                    FrameworkSatisfactionStatus.UNKNOWN,
                    (),
                    ("not_applicable_approval_expired_or_outside_cutoff",),
                )
            return _control_result(
                specification,
                decision.status,
                mapping_state,
                FrameworkEvaluationStatus.EVALUATED,
                FrameworkSatisfactionStatus.NOT_APPLICABLE,
                (),
                ("approved_not_applicable",),
            )

        requirement_results: list[FrameworkRequirementResult] = []
        for requirement in specification.evidence:
            matching = tuple(
                item for item in evidence if item.requirement_id == requirement.requirement_id
            )
            requirement_results.append(_evaluate_requirement(requirement, request, matching))
        supporting_candidates = tuple(
            item for item in evidence if item.evidence_role is FrameworkEvidenceRole.SUPPORTING_ONLY
        )
        supporting: list[FrameworkEvidenceReceipt] = []
        supporting_limitations: set[str] = set()
        for item in supporting_candidates:
            reason = _supporting_inadmissible_reason(request, item)
            if reason is None:
                supporting.append(item)
            else:
                supporting_limitations.add(f"supporting_{reason}")
        statuses = tuple(item.status for item in requirement_results)
        satisfaction = _combine_requirement_statuses(specification.requirement_mode, statuses)
        limitations = {
            limitation for item in requirement_results for limitation in item.limitations
        } | supporting_limitations
        if supporting:
            limitations.add("supporting_evidence_only")
        evaluation = (
            FrameworkEvaluationStatus.EVALUATED
            if satisfaction
            in {
                FrameworkSatisfactionStatus.SATISFIED,
                FrameworkSatisfactionStatus.FAILED,
            }
            else FrameworkEvaluationStatus.BLOCKED
            if any(item.blocked_dependency for item in specification.evidence)
            else FrameworkEvaluationStatus.NOT_EVALUATED
        )
        return _control_result(
            specification,
            decision.status,
            mapping_state,
            evaluation,
            satisfaction,
            tuple(requirement_results),
            tuple(sorted(limitations)),
            supporting=tuple(supporting),
        )

    def _validate_tradeoffs(
        self,
        request: FrameworkAssessmentRequest,
        expected_ids: tuple[str, ...],
    ) -> None:
        known = set(expected_ids)
        for tradeoff in request.tradeoffs:
            if tradeoff.scope_digest != request.profile.scope_digest:
                raise ValueError("framework tradeoff scope does not match the assessment")
            if not set(tradeoff.affected_control_ids).issubset(known):
                raise ValueError("framework tradeoff references an unknown control")
            if (
                tradeoff.approved_at > request.evaluated_at
                or tradeoff.expires_at <= request.evaluated_at
            ):
                raise ValueError("framework tradeoff approval is outside the evaluation window")


def _mapping_state(specification: FrameworkControlSpecification) -> str:
    states = {item.relationship for item in specification.crosswalk}
    if FrameworkRelationshipState.FULL in states:
        return "full"
    if states - {FrameworkRelationshipState.UNMAPPED}:
        return "partial"
    return "unmapped"


def _evaluate_requirement(
    requirement: FrameworkEvidenceSpecification,
    request: FrameworkAssessmentRequest,
    evidence: tuple[FrameworkEvidenceReceipt, ...],
) -> FrameworkRequirementResult:
    limitations: set[str] = set()
    admitted: list[FrameworkEvidenceReceipt] = []
    for receipt in evidence:
        # Producer limitation codes explain an unknown outcome whether or not it is admitted.
        limitations.update(receipt.limitations)
        reason = _inadmissible_reason(requirement, request, receipt)
        if reason is None:
            admitted.append(receipt)
        else:
            limitations.add(reason)
    if requirement.blocked_dependency is not None:
        limitations.add(f"blocked_dependency:{requirement.blocked_dependency}")
    decisive = [item for item in admitted if item.evidence_role is FrameworkEvidenceRole.DECISIVE]
    supporting = [
        item for item in admitted if item.evidence_role is FrameworkEvidenceRole.SUPPORTING_ONLY
    ]
    if supporting:
        limitations.add("supporting_evidence_only")
    if not decisive:
        limitations.add("decisive_evidence_unavailable")
        status = FrameworkSatisfactionStatus.UNKNOWN
    else:
        outcomes = {item.outcome for item in decisive}
        if len(outcomes) != 1:
            limitations.add("evidence_conflict")
            status = FrameworkSatisfactionStatus.UNKNOWN
        else:
            status = next(iter(outcomes))
            if status is FrameworkSatisfactionStatus.NOT_APPLICABLE:
                if any(
                    item.approval_expires_at is None
                    or item.approval_expires_at <= request.evaluated_at
                    for item in decisive
                ):
                    limitations.add("not_applicable_approval_expired")
                    status = FrameworkSatisfactionStatus.UNKNOWN
    if requirement.generation_contract is FrameworkGenerationContract.NONE and any(
        item.inventory_generation is not None or item.hierarchy_generation is not None
        for item in decisive
    ):
        limitations.add("unexpected_generation_binding")
        status = FrameworkSatisfactionStatus.UNKNOWN
    return FrameworkRequirementResult(
        requirement_id=requirement.requirement_id,
        status=status,
        evidence_refs=tuple(sorted({item.evidence_ref for item in admitted})),
        evidence_digests=tuple(sorted({item.evidence_digest for item in admitted})),
        limitations=tuple(sorted(limitations)),
    )


def _inadmissible_reason(
    requirement: FrameworkEvidenceSpecification,
    request: FrameworkAssessmentRequest,
    receipt: FrameworkEvidenceReceipt,
) -> str | None:
    profile = request.profile
    if receipt.framework_id != profile.framework_id:
        return "wrong_framework"
    if receipt.scope_digest != profile.scope_digest:
        return "wrong_scope"
    if receipt.recorded_at > request.recorded_at or receipt.observed_at > request.evaluated_at:
        return "evidence_after_cutoff"
    if (
        receipt.observed_at
        + timedelta(
            seconds=min(
                receipt.freshness_ceiling_seconds,
                requirement.freshness_ceiling_seconds,
            )
        )
        <= request.evaluated_at
    ):
        return "stale_evidence"
    if receipt.producer != requirement.authoritative_producer:
        return "wrong_producer"
    if receipt.evidence_kind != requirement.kind.value:
        return "wrong_evidence_kind"
    if (
        receipt.evidence_role is FrameworkEvidenceRole.DECISIVE
        and receipt.evidence_role is not requirement.evidence_role
    ):
        return "wrong_evidence_role"
    if receipt.process_phase is not requirement.process_phase:
        return "wrong_process_phase"
    if receipt.provider_error:
        return "provider_error"
    if requirement.completeness_required and not receipt.complete:
        return "incomplete_evidence"
    if receipt.truncated:
        return "truncated_evidence"
    if receipt.conflicting:
        return "conflicting_evidence"
    if receipt.synthetic:
        return "synthetic_evidence"
    if requirement.generation_contract is FrameworkGenerationContract.INVENTORY:
        if (
            not receipt.inventory_generation
            or receipt.inventory_generation != profile.inventory_generation
            or receipt.hierarchy_generation is not None
        ):
            return "wrong_inventory_generation"
    if requirement.generation_contract is FrameworkGenerationContract.HIERARCHY:
        if (
            not receipt.hierarchy_generation
            or receipt.hierarchy_generation != profile.hierarchy_generation
            or receipt.inventory_generation is not None
        ):
            return "wrong_hierarchy_generation"
    if requirement.kind is FrameworkRequirementKind.RULE:
        # The profile pin is read independently, so a receipt cannot vouch for its own generation.
        if profile.rule_activation is None:
            return "rule_activation_unpinned"
        if receipt.rule_provenance is None:
            return "rule_provenance_missing"
        if receipt.rule_provenance.activation != profile.rule_activation:
            return "rule_activation_mismatch"
    return None


def _supporting_inadmissible_reason(
    request: FrameworkAssessmentRequest,
    receipt: FrameworkEvidenceReceipt,
) -> str | None:
    profile = request.profile
    if receipt.framework_id != profile.framework_id:
        return "wrong_framework"
    if receipt.scope_digest != profile.scope_digest:
        return "wrong_scope"
    if receipt.recorded_at > request.recorded_at or receipt.observed_at > request.evaluated_at:
        return "evidence_after_cutoff"
    if (
        receipt.observed_at + timedelta(seconds=receipt.freshness_ceiling_seconds)
        <= request.evaluated_at
    ):
        return "stale_evidence"
    if receipt.provider_error:
        return "provider_error"
    if not receipt.complete:
        return "incomplete_evidence"
    if receipt.truncated:
        return "truncated_evidence"
    if receipt.conflicting:
        return "conflicting_evidence"
    if receipt.synthetic:
        return "synthetic_evidence"
    if profile.inventory_generation is not None and (
        receipt.inventory_generation != profile.inventory_generation
        or receipt.hierarchy_generation is not None
    ):
        return "wrong_inventory_generation"
    if profile.hierarchy_generation is not None and (
        receipt.hierarchy_generation != profile.hierarchy_generation
        or receipt.inventory_generation is not None
    ):
        return "wrong_hierarchy_generation"
    return None


def _combine_requirement_statuses(
    mode: str,
    statuses: tuple[FrameworkSatisfactionStatus, ...],
) -> FrameworkSatisfactionStatus:
    applicable = tuple(
        item for item in statuses if item is not FrameworkSatisfactionStatus.NOT_APPLICABLE
    )
    if not applicable:
        return FrameworkSatisfactionStatus.UNKNOWN
    if mode == "any" and FrameworkSatisfactionStatus.SATISFIED in applicable:
        return FrameworkSatisfactionStatus.SATISFIED
    if mode == "all" and all(item is FrameworkSatisfactionStatus.SATISFIED for item in applicable):
        return FrameworkSatisfactionStatus.SATISFIED
    if FrameworkSatisfactionStatus.FAILED in applicable:
        return FrameworkSatisfactionStatus.FAILED
    return FrameworkSatisfactionStatus.UNKNOWN


def _control_result(
    specification: FrameworkControlSpecification,
    applicability: FrameworkApplicabilityStatus,
    mapping_state: str,
    evaluation: FrameworkEvaluationStatus,
    satisfaction: FrameworkSatisfactionStatus,
    requirements: tuple[FrameworkRequirementResult, ...],
    limitations: tuple[str, ...],
    *,
    supporting: tuple[FrameworkEvidenceReceipt, ...] = (),
) -> FrameworkControlResult:
    evidence_refs = {reference for item in requirements for reference in item.evidence_refs} | {
        item.evidence_ref for item in supporting
    }
    evidence_digests = {digest for item in requirements for digest in item.evidence_digests} | {
        item.evidence_digest for item in supporting
    }
    return FrameworkControlResult(
        control_id=specification.control_id,
        title=specification.title,
        area=specification.area,
        reference_state="present",
        mapping_state=mapping_state,
        applicability=applicability,
        evaluation=evaluation,
        satisfaction=satisfaction,
        owner_slot=specification.owner_slot,
        cadence_days=specification.cadence_days,
        evidence_complete=bool(requirements)
        and all(
            item.status
            in {
                FrameworkSatisfactionStatus.SATISFIED,
                FrameworkSatisfactionStatus.FAILED,
                FrameworkSatisfactionStatus.NOT_APPLICABLE,
            }
            for item in requirements
        ),
        evidence_refs=tuple(sorted(evidence_refs)),
        evidence_digests=tuple(sorted(evidence_digests)),
        limitations=limitations,
        requirements=requirements,
    )


class FrameworkAssessmentService:
    """Audit and publish one immutable shadow result through event ingress."""

    def __init__(
        self,
        runtime: FrameworkAssessmentRuntime,
        state_store: FrameworkAssessmentAuditStore,
        event_bus: FrameworkAssessmentPublisher,
    ) -> None:
        self._runtime = runtime
        self._state_store = state_store
        self._event_bus = event_bus

    async def assess(self, request: FrameworkAssessmentRequest) -> FrameworkAssessmentResult:
        result = self._runtime.assess(request)
        await self._state_store.append_audit_entry(
            {
                "type": "framework_shadow_assessment",
                "assessment_id": result.assessment_id,
                "framework_id": result.framework_id,
                "profile_digest": result.profile_digest,
                "scope_digest": result.scope_digest,
                "result_digest": result.result_digest,
                "execution_authority": False,
                "recorded_at": result.recorded_at.isoformat(),
            }
        )
        await self._event_bus.publish(
            FRAMEWORK_ASSESSMENT_TOPIC,
            result.assessment_id,
            result.to_dict(),
        )
        return result


def replay_framework_assessment(
    runtime: FrameworkAssessmentRuntime,
    request: FrameworkAssessmentRequest,
    expected_digest: str,
) -> FrameworkAssessmentResult:
    """Recompute one result and reject a stored digest mismatch."""

    result = runtime.assess(request)
    if result.result_digest != expected_digest:
        raise ValueError("framework assessment replay digest mismatch")
    return result


__all__ = [
    "FRAMEWORK_ASSESSMENT_TOPIC",
    "FrameworkAssessmentAuditStore",
    "FrameworkAssessmentPublisher",
    "FrameworkAssessmentRuntime",
    "FrameworkAssessmentService",
    "replay_framework_assessment",
]
