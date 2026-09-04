"""Deterministic shadow-only WARA assessment and publication."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai_service_contracts.wara_assessment import WARA_ASSESSMENT_TOPIC

from fdai.rule_catalog.schema.wara_assessment import (
    QuerySafetyClassification,
    ResourceTypeDisposition,
    WaraAssessmentCatalog,
    WaraDisposition,
    WaraRecommendationCrosswalk,
    canonical_digest,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import (
    WaraEvaluatorBinding,
    WaraEvaluatorBindingCatalog,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.wara_assessment import (
    WaraAssessmentObservationProvider,
    WaraObservationError,
    WaraObservationReceipt,
    WaraReadPlan,
)


class WaraApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class WaraEvaluationStatus(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"


class WaraSatisfactionStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WaraScopedResource:
    resource_id: str
    provider_resource_type: str
    workload_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or not self.provider_resource_type.strip():
            raise ValueError("WARA scoped resource requires identity and provider type")
        if self.workload_tags != tuple(sorted(set(self.workload_tags))):
            raise ValueError("WARA scoped resource tags MUST be unique and ordered")


@dataclass(frozen=True, slots=True)
class WaraEvidenceReceipt:
    recommendation_id: str
    evidence_ref: str
    evidence_kind: str
    producer: str
    scope_digest: str
    source_revision: str
    inventory_generation: str
    observed_at: datetime
    recorded_at: datetime
    evidence_digest: str
    freshness_ceiling_seconds: int
    complete: bool
    truncated: bool
    conflicting: bool
    synthetic: bool
    provider_error: str | None
    outcome: WaraSatisfactionStatus
    applicability_approval_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.evidence_ref.strip()
            or not self.evidence_kind.strip()
            or not self.producer.strip()
        ):
            raise ValueError("WARA evidence identity fields MUST be non-empty")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", self.evidence_digest) is None:
            raise ValueError("WARA evidence digest MUST be lowercase SHA-256")
        if self.observed_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("WARA evidence timestamps MUST be timezone-aware")
        if self.recorded_at < self.observed_at:
            raise ValueError("WARA evidence recorded_at MUST follow observed_at")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("WARA evidence freshness ceiling MUST be positive")


@dataclass(frozen=True, slots=True)
class WaraAssessmentRequest:
    assessment_id: str
    framework_revision: str
    crosswalk_digest: str
    ontology_release: str
    inventory_generation: str
    workload_id: str
    resources: tuple[WaraScopedResource, ...]
    evaluated_at: datetime
    recorded_at: datetime
    evaluator_bindings_digest: str | None = None
    evidence: tuple[WaraEvidenceReceipt, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.assessment_id,
                self.framework_revision,
                self.crosswalk_digest,
                self.ontology_release,
                self.inventory_generation,
                self.workload_id,
            )
        ):
            raise ValueError("WARA assessment request pins MUST be non-empty")
        if not self.resources:
            raise ValueError("WARA assessment requires at least one scoped resource")
        resource_ids = tuple(item.resource_id for item in self.resources)
        if resource_ids != tuple(sorted(set(resource_ids))):
            raise ValueError("WARA assessment resources MUST be unique and ordered")
        if self.evaluated_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("WARA assessment timestamps MUST be timezone-aware")
        if self.recorded_at < self.evaluated_at:
            raise ValueError("WARA assessment recorded_at MUST follow evaluated_at")
        if (
            self.evaluator_bindings_digest is not None
            and re.fullmatch(r"sha256:[a-f0-9]{64}", self.evaluator_bindings_digest) is None
        ):
            raise ValueError("WARA evaluator bindings digest MUST be lowercase SHA-256")

    @property
    def scope_digest(self) -> str:
        return canonical_digest(
            {
                "workload_id": self.workload_id,
                "resources": [
                    {
                        "resource_id": item.resource_id,
                        "provider_resource_type": item.provider_resource_type.casefold(),
                        "workload_tags": list(item.workload_tags),
                    }
                    for item in self.resources
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class WaraControlResult:
    recommendation_id: str
    catalog_state: str
    mapping_state: str
    applicability: WaraApplicabilityStatus
    evaluation: WaraEvaluationStatus
    satisfaction: WaraSatisfactionStatus
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    evidence_complete: bool
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "catalog_state": self.catalog_state,
            "mapping_state": self.mapping_state,
            "applicability": self.applicability.value,
            "evaluation": self.evaluation.value,
            "satisfaction": self.satisfaction.value,
            "evidence_refs": list(self.evidence_refs),
            "evidence_digests": list(self.evidence_digests),
            "evidence_complete": self.evidence_complete,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class WaraAssessmentResult:
    assessment_id: str
    mode: str
    execution_authority: bool
    framework_revision: str
    crosswalk_digest: str
    evaluator_bindings_digest: str | None
    ontology_release: str
    inventory_generation: str
    workload_id: str
    scope_digest: str
    evaluated_at: datetime
    recorded_at: datetime
    controls: tuple[WaraControlResult, ...]
    aggregate_counts: dict[str, int]
    result_digest: str

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "assessment_id": self.assessment_id,
            "mode": self.mode,
            "execution_authority": self.execution_authority,
            "framework_revision": self.framework_revision,
            "crosswalk_digest": self.crosswalk_digest,
            "ontology_release": self.ontology_release,
            "inventory_generation": self.inventory_generation,
            "workload_id": self.workload_id,
            "scope_digest": self.scope_digest,
            "evaluated_at": self.evaluated_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "controls": [item.to_dict() for item in self.controls],
            "aggregate_counts": dict(sorted(self.aggregate_counts.items())),
        }
        if self.evaluator_bindings_digest is not None:
            value["evaluator_bindings_digest"] = self.evaluator_bindings_digest
        if include_digest:
            value["result_digest"] = self.result_digest
        return value


class WaraAssessmentRuntime:
    """Evaluate the conservative crosswalk without I/O or execution authority."""

    def __init__(
        self,
        catalog: WaraAssessmentCatalog,
        evaluator_bindings: WaraEvaluatorBindingCatalog | None = None,
    ) -> None:
        if evaluator_bindings is not None and (
            evaluator_bindings.source_revision != catalog.source_revision
            or evaluator_bindings.crosswalk_digest != catalog.crosswalk_digest
        ):
            raise ValueError("WARA evaluator bindings do not match the assessment catalog")
        self._catalog = catalog
        self._evaluator_bindings = evaluator_bindings

    @property
    def recommendations(self) -> tuple[WaraRecommendationCrosswalk, ...]:
        """Return the immutable generated recommendation set."""

        return self._catalog.recommendations

    def assess(self, request: WaraAssessmentRequest) -> WaraAssessmentResult:
        if request.framework_revision != self._catalog.source_revision:
            raise ValueError("WARA assessment framework revision mismatch")
        if request.crosswalk_digest != self._catalog.crosswalk_digest:
            raise ValueError("WARA assessment crosswalk digest mismatch")
        expected_bindings_digest = (
            self._evaluator_bindings.overlay_digest
            if self._evaluator_bindings is not None
            else None
        )
        if request.evaluator_bindings_digest != expected_bindings_digest:
            raise ValueError("WARA assessment evaluator bindings digest mismatch")
        evidence_by_id = _index_evidence(request.evidence)
        controls = tuple(
            self._evaluate_control(record, request, evidence_by_id.get(record.aprl_guid, ()))
            for record in self._catalog.recommendations
        )
        counts: dict[str, int] = {}
        for control in controls:
            for key, value in (
                ("catalog.active", control.catalog_state),
                ("mapping", control.mapping_state),
                ("applicability", control.applicability.value),
                ("evaluation", control.evaluation.value),
                ("satisfaction", control.satisfaction.value),
            ):
                count_key = f"{key}.{value}" if key != "catalog.active" else "catalog.active"
                counts[count_key] = counts.get(count_key, 0) + 1
        material: dict[str, Any] = {
            "assessment_id": request.assessment_id,
            "mode": "shadow",
            "execution_authority": False,
            "framework_revision": request.framework_revision,
            "crosswalk_digest": request.crosswalk_digest,
            "ontology_release": request.ontology_release,
            "inventory_generation": request.inventory_generation,
            "workload_id": request.workload_id,
            "scope_digest": request.scope_digest,
            "evaluated_at": request.evaluated_at,
            "recorded_at": request.recorded_at,
            "controls": controls,
            "aggregate_counts": counts,
        }
        digest_material = {
            **material,
            "evaluated_at": request.evaluated_at.isoformat(),
            "recorded_at": request.recorded_at.isoformat(),
            "controls": [item.to_dict() for item in controls],
            "aggregate_counts": dict(sorted(counts.items())),
        }
        if request.evaluator_bindings_digest is not None:
            digest_material["evaluator_bindings_digest"] = request.evaluator_bindings_digest
        return WaraAssessmentResult(
            **material,
            evaluator_bindings_digest=request.evaluator_bindings_digest,
            result_digest=canonical_digest(digest_material),
        )

    def _evaluate_control(
        self,
        record: WaraRecommendationCrosswalk,
        request: WaraAssessmentRequest,
        evidence: tuple[WaraEvidenceReceipt, ...],
    ) -> WaraControlResult:
        limitations: list[str] = []
        mapping = record.applicability
        binding = _binding_for(record, self._evaluator_bindings)
        evaluator_ref, blocked_reasons = _resolved_query_evaluator(record, binding)
        matching = tuple(
            resource
            for resource in request.resources
            if resource.provider_resource_type.casefold() == mapping.normalized_provider_type
            and set(record.workload_tags).issubset(resource.workload_tags)
        )
        if mapping.disposition is not ResourceTypeDisposition.CANONICAL:
            limitations.append("unsupported_resource_type")
        if not matching:
            limitations.append("scope_not_observed")
        query_admitted = _query_is_admitted(record, binding, evaluator_ref, blocked_reasons)
        if record.disposition is WaraDisposition.AMBIGUOUS_OR_BLOCKED and not query_admitted:
            limitations.append("crosswalk_blocked")
            if record.query_review is not None:
                limitations.extend(blocked_reasons)
        applicability = (
            WaraApplicabilityStatus.APPLICABLE
            if matching and mapping.disposition is ResourceTypeDisposition.CANONICAL
            else WaraApplicabilityStatus.UNKNOWN
        )
        if record.disposition is WaraDisposition.AMBIGUOUS_OR_BLOCKED and not query_admitted:
            return _control_result(
                record,
                applicability,
                WaraEvaluationStatus.BLOCKED,
                WaraSatisfactionStatus.UNKNOWN,
                evidence,
                limitations,
            )
        if applicability is not WaraApplicabilityStatus.APPLICABLE:
            limitations.append("applicability_unknown")
            return _control_result(
                record,
                applicability,
                WaraEvaluationStatus.NOT_EVALUATED,
                WaraSatisfactionStatus.UNKNOWN,
                evidence,
                limitations,
            )
        admitted = tuple(
            receipt
            for receipt in evidence
            if _receipt_admitted(receipt, request, record, evaluator_ref=evaluator_ref)
        )
        if not admitted:
            limitations.append("evidence_unavailable_or_inadmissible")
            return _control_result(
                record,
                applicability,
                WaraEvaluationStatus.NOT_EVALUATED,
                WaraSatisfactionStatus.UNKNOWN,
                evidence,
                limitations,
            )

        outcomes = {item.outcome for item in admitted}
        if outcomes == {WaraSatisfactionStatus.NOT_APPLICABLE}:
            applicability = WaraApplicabilityStatus.NOT_APPLICABLE
            satisfaction = WaraSatisfactionStatus.NOT_APPLICABLE
        elif outcomes == {WaraSatisfactionStatus.SATISFIED}:
            satisfaction = WaraSatisfactionStatus.SATISFIED
        elif WaraSatisfactionStatus.FAILED in outcomes:
            satisfaction = WaraSatisfactionStatus.FAILED
        else:
            satisfaction = WaraSatisfactionStatus.UNKNOWN
        return _control_result(
            record,
            applicability,
            WaraEvaluationStatus.EVALUATED,
            satisfaction,
            admitted,
            limitations,
        )

    def build_read_plan(
        self,
        record: WaraRecommendationCrosswalk,
        request: WaraAssessmentRequest,
    ) -> WaraReadPlan:
        """Build one plan using this runtime's pinned evaluator overlay."""

        return build_wara_read_plan(
            record,
            request,
            evaluator_bindings=self._evaluator_bindings,
        )


@dataclass(frozen=True, slots=True)
class WaraObservationAttempt:
    """One bounded observation attempt included in the assessment audit."""

    recommendation_id: str
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WaraObservationCollection:
    """Request enriched with provider evidence and bounded attempt outcomes."""

    request: WaraAssessmentRequest
    attempts: tuple[WaraObservationAttempt, ...]


class WaraAssessmentObservationRunner:
    """Collect every exact-bound provider observation before shadow assessment."""

    def __init__(
        self,
        *,
        runtime: WaraAssessmentRuntime,
        provider: WaraAssessmentObservationProvider,
    ) -> None:
        self._runtime = runtime
        self._provider = provider

    async def collect(self, request: WaraAssessmentRequest) -> WaraObservationCollection:
        """Return exact evidence while preserving manual and caller-supplied receipts."""

        evidence = {
            (item.recommendation_id, item.evidence_ref): _bind_caller_evidence_cutoff(
                item,
                request,
            )
            for item in request.evidence
        }
        if len(evidence) != len(request.evidence):
            raise ValueError("WARA request evidence contains duplicate references")
        attempts: list[WaraObservationAttempt] = []
        collected_evidence: list[WaraEvidenceReceipt] = []
        for record in self._runtime.recommendations:
            try:
                plan = self._runtime.build_read_plan(record, request)
            except ValueError:
                continue
            try:
                receipt = await self._provider.observe(plan)
            except WaraObservationError:
                attempts.append(
                    WaraObservationAttempt(
                        recommendation_id=record.aprl_guid,
                        status="unavailable",
                        reason="provider_observation_unavailable",
                    )
                )
                continue
            item = wara_observation_to_evidence(plan, receipt, request)
            key = (item.recommendation_id, item.evidence_ref)
            existing = evidence.get(key)
            if existing is not None and existing != item:
                raise ValueError("WARA collected evidence conflicts with an existing receipt")
            evidence[key] = item
            collected_evidence.append(item)
            attempts.append(
                WaraObservationAttempt(
                    recommendation_id=record.aprl_guid,
                    status="observed",
                )
            )
        latest_observed_at = max(
            (request.evaluated_at, *(item.observed_at for item in collected_evidence))
        )
        latest_recorded_at = max(
            (
                request.recorded_at,
                latest_observed_at,
                *(item.recorded_at for item in collected_evidence),
            )
        )
        enriched = replace(
            request,
            evaluated_at=latest_observed_at,
            recorded_at=latest_recorded_at,
            evidence=tuple(
                evidence[key] for key in sorted(evidence, key=lambda item: (item[0], item[1]))
            ),
        )
        return WaraObservationCollection(request=enriched, attempts=tuple(attempts))


def _bind_caller_evidence_cutoff(
    item: WaraEvidenceReceipt,
    request: WaraAssessmentRequest,
) -> WaraEvidenceReceipt:
    """Keep caller evidence inadmissible when it exceeds the original request cutoff."""

    if item.observed_at <= request.evaluated_at and item.recorded_at <= request.recorded_at:
        return item
    return replace(
        item,
        provider_error=item.provider_error or "caller_evidence_after_original_cutoff",
    )


class WaraAssessmentService:
    """Persist audit evidence and publish one shadow result through event ingress."""

    def __init__(
        self,
        runtime: WaraAssessmentRuntime,
        state_store: StateStore,
        event_bus: EventBus,
        observation_runner: WaraAssessmentObservationRunner | None = None,
    ):
        self._runtime = runtime
        self._state_store = state_store
        self._event_bus = event_bus
        self._observation_runner = observation_runner

    async def assess(self, request: WaraAssessmentRequest) -> WaraAssessmentResult:
        attempts: tuple[WaraObservationAttempt, ...] = ()
        if self._observation_runner is not None:
            collection = await self._observation_runner.collect(request)
            request = collection.request
            attempts = collection.attempts
        result = self._runtime.assess(request)
        payload = result.to_dict()
        await self._state_store.append_audit_entry(
            {
                "type": "wara_shadow_assessment",
                "assessment_id": result.assessment_id,
                "result_digest": result.result_digest,
                "scope_digest": result.scope_digest,
                "execution_authority": False,
                "observation_attempts": [
                    {
                        "recommendation_id": item.recommendation_id,
                        "status": item.status,
                        "reason": item.reason,
                    }
                    for item in attempts
                ],
                "recorded_at": result.recorded_at.isoformat(),
            }
        )
        await self._event_bus.publish(
            WARA_ASSESSMENT_TOPIC,
            result.assessment_id,
            payload,
        )
        return result


def replay_wara_assessment(
    runtime: WaraAssessmentRuntime,
    request: WaraAssessmentRequest,
    expected_digest: str,
) -> WaraAssessmentResult:
    """Recompute one result and reject an audit digest mismatch."""

    result = runtime.assess(request)
    if result.result_digest != expected_digest:
        raise ValueError("WARA assessment replay digest mismatch")
    return result


def build_wara_read_plan(
    record: WaraRecommendationCrosswalk,
    request: WaraAssessmentRequest,
    *,
    evaluator_bindings: WaraEvaluatorBindingCatalog | None = None,
) -> WaraReadPlan:
    """Normalize one reviewed external query into an exact bounded read plan."""

    review = record.query_review
    binding = _binding_for(record, evaluator_bindings)
    evaluator_ref, blocked_reasons = _resolved_query_evaluator(record, binding)
    expected_bindings_digest = (
        evaluator_bindings.overlay_digest if evaluator_bindings is not None else None
    )
    if request.evaluator_bindings_digest != expected_bindings_digest:
        raise ValueError("WARA read plan evaluator bindings digest mismatch")
    if (
        review is None
        or review.safety_classification is not QuerySafetyClassification.READ_ONLY_BOUNDED
        or evaluator_ref is None
        or blocked_reasons
        or not _query_is_admitted(record, binding, evaluator_ref, blocked_reasons)
    ):
        raise ValueError("WARA recommendation has no admitted read-only query")
    matching = tuple(
        sorted(
            resource.resource_id
            for resource in request.resources
            if resource.provider_resource_type.casefold()
            == record.applicability.normalized_provider_type
            and set(record.workload_tags).issubset(resource.workload_tags)
        )
    )
    if not matching:
        raise ValueError("WARA read plan has no exact resource scope")
    return WaraReadPlan(
        recommendation_id=record.aprl_guid,
        query_digest=review.body_digest,
        evaluator_ref=evaluator_ref,
        evaluator_bindings_digest=(
            evaluator_bindings.overlay_digest
            if evaluator_bindings is not None
            else canonical_digest(
                {
                    "aprl_guid": record.aprl_guid,
                    "evaluator_ref": evaluator_ref,
                    "query_digest": review.body_digest,
                }
            )
        ),
        workload_id=request.workload_id,
        resource_ids=matching,
        provider_resource_types=(record.applicability.normalized_provider_type,),
        inventory_generation=request.inventory_generation,
        maximum_rows=review.maximum_rows,
        timeout_seconds=review.timeout_seconds,
        evidence_freshness_ceiling_seconds=(review.evidence_freshness_ceiling_seconds),
    )


def wara_observation_to_evidence(
    plan: WaraReadPlan,
    receipt: WaraObservationReceipt,
    request: WaraAssessmentRequest,
) -> WaraEvidenceReceipt:
    """Convert one exact provider receipt into runtime-admissible evidence."""

    if (
        receipt.recommendation_id != plan.recommendation_id
        or receipt.query_digest != plan.query_digest
        or receipt.evaluator_ref != plan.evaluator_ref
        or receipt.evaluator_bindings_digest != plan.evaluator_bindings_digest
        or receipt.workload_id != plan.workload_id
        or receipt.resource_ids != plan.resource_ids
        or receipt.inventory_generation != plan.inventory_generation
    ):
        raise ValueError("WARA observation receipt does not match the read plan")
    if receipt.satisfied is None:
        raise ValueError("WARA observation receipt has no deterministic evaluator outcome")
    return WaraEvidenceReceipt(
        recommendation_id=receipt.recommendation_id,
        evidence_ref=f"wara-observation:{receipt.evidence_digest.removeprefix('sha256:')}",
        evidence_kind="provider_observation",
        producer=receipt.evaluator_ref,
        scope_digest=request.scope_digest,
        source_revision=request.framework_revision,
        inventory_generation=receipt.inventory_generation,
        observed_at=receipt.observed_at,
        recorded_at=receipt.recorded_at,
        evidence_digest=receipt.evidence_digest,
        freshness_ceiling_seconds=plan.evidence_freshness_ceiling_seconds,
        complete=receipt.complete,
        truncated=receipt.truncated,
        conflicting=receipt.conflicting,
        synthetic=receipt.synthetic,
        provider_error=None,
        outcome=(
            WaraSatisfactionStatus.SATISFIED if receipt.satisfied else WaraSatisfactionStatus.FAILED
        ),
    )


def _binding_for(
    record: WaraRecommendationCrosswalk,
    evaluator_bindings: WaraEvaluatorBindingCatalog | None,
) -> WaraEvaluatorBinding | None:
    review = record.query_review
    if evaluator_bindings is None or review is None:
        return None
    return evaluator_bindings.resolve(record.aprl_guid, review.body_digest)


def _resolved_query_evaluator(
    record: WaraRecommendationCrosswalk,
    binding: WaraEvaluatorBinding | None,
) -> tuple[str | None, tuple[str, ...]]:
    review = record.query_review
    if review is None:
        return None, ()
    evaluator_ref = review.evaluator_ref
    blocked_reasons = set(review.blocked_reasons)
    if binding is not None:
        evaluator_ref = binding.evaluator_ref
        blocked_reasons.discard("missing_exact_evaluator")
    return evaluator_ref, tuple(sorted(blocked_reasons))


def _query_is_admitted(
    record: WaraRecommendationCrosswalk,
    binding: WaraEvaluatorBinding | None,
    evaluator_ref: str | None,
    blocked_reasons: tuple[str, ...],
) -> bool:
    review = record.query_review
    if (
        review is None
        or review.safety_classification is not QuerySafetyClassification.READ_ONLY_BOUNDED
        or evaluator_ref is None
        or blocked_reasons
    ):
        return False
    return record.disposition in {
        WaraDisposition.EXISTING_RULE,
        WaraDisposition.NEW_RULE_CANDIDATE,
    } or (binding is not None and record.disposition is WaraDisposition.AMBIGUOUS_OR_BLOCKED)


def _index_evidence(
    evidence: tuple[WaraEvidenceReceipt, ...],
) -> dict[str, tuple[WaraEvidenceReceipt, ...]]:
    indexed: dict[str, list[WaraEvidenceReceipt]] = {}
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.recommendation_id, item.evidence_ref)
        if key in seen:
            raise ValueError("WARA evidence references MUST be unique per recommendation")
        seen.add(key)
        indexed.setdefault(item.recommendation_id, []).append(item)
    return {
        key: tuple(sorted(values, key=lambda item: item.evidence_ref))
        for key, values in indexed.items()
    }


def _receipt_admitted(
    receipt: WaraEvidenceReceipt,
    request: WaraAssessmentRequest,
    record: WaraRecommendationCrosswalk,
    *,
    evaluator_ref: str | None,
) -> bool:
    if (
        receipt.recommendation_id != record.aprl_guid
        or receipt.scope_digest != request.scope_digest
        or receipt.source_revision != request.framework_revision
        or receipt.inventory_generation != request.inventory_generation
        or receipt.provider_error is not None
        or not receipt.complete
        or receipt.truncated
        or receipt.conflicting
        or receipt.synthetic
        or receipt.observed_at > request.evaluated_at
        or receipt.recorded_at > request.recorded_at
    ):
        return False
    requirement = record.manual_evidence
    if requirement is not None:
        if (
            receipt.evidence_kind != requirement.kind
            or receipt.producer != requirement.authoritative_producer
            or receipt.freshness_ceiling_seconds != requirement.freshness_ceiling_seconds
        ):
            return False
        freshness_ceiling_seconds = requirement.freshness_ceiling_seconds
    else:
        review = record.query_review
        if review is None or evaluator_ref is None:
            return False
        if (
            receipt.evidence_kind != "provider_observation"
            or receipt.producer != evaluator_ref
            or receipt.freshness_ceiling_seconds != review.evidence_freshness_ceiling_seconds
        ):
            return False
        freshness_ceiling_seconds = review.evidence_freshness_ceiling_seconds
    if request.evaluated_at - receipt.observed_at > timedelta(seconds=freshness_ceiling_seconds):
        return False
    if receipt.outcome is WaraSatisfactionStatus.NOT_APPLICABLE:
        return (
            record.disposition is WaraDisposition.CONDITIONAL_NOT_APPLICABLE
            and receipt.applicability_approval_ref is not None
        )
    return receipt.outcome in {
        WaraSatisfactionStatus.SATISFIED,
        WaraSatisfactionStatus.FAILED,
    }


def _control_result(
    record: WaraRecommendationCrosswalk,
    applicability: WaraApplicabilityStatus,
    evaluation: WaraEvaluationStatus,
    satisfaction: WaraSatisfactionStatus,
    evidence: tuple[WaraEvidenceReceipt, ...],
    limitations: list[str],
) -> WaraControlResult:
    return WaraControlResult(
        recommendation_id=record.aprl_guid,
        catalog_state="active",
        mapping_state=record.mapping_state.value,
        applicability=applicability,
        evaluation=evaluation,
        satisfaction=satisfaction,
        evidence_refs=tuple(sorted(item.evidence_ref for item in evidence)),
        evidence_digests=tuple(sorted(item.evidence_digest for item in evidence)),
        evidence_complete=(evaluation is WaraEvaluationStatus.EVALUATED and bool(evidence)),
        limitations=tuple(sorted(set(limitations))),
    )


__all__ = [
    "WARA_ASSESSMENT_TOPIC",
    "WaraApplicabilityStatus",
    "WaraAssessmentRequest",
    "WaraAssessmentResult",
    "WaraAssessmentRuntime",
    "WaraAssessmentObservationRunner",
    "WaraAssessmentService",
    "WaraControlResult",
    "WaraEvaluationStatus",
    "WaraObservationAttempt",
    "WaraObservationCollection",
    "WaraEvidenceReceipt",
    "WaraSatisfactionStatus",
    "WaraScopedResource",
    "build_wara_read_plan",
    "replay_wara_assessment",
    "wara_observation_to_evidence",
]
