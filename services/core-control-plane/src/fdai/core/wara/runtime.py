"""Deterministic shadow-only WARA assessment and publication."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import timedelta
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
from fdai.rule_catalog.schema.wara_rule_binding import WaraRuleBinding, WaraRuleBindingCatalog
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.wara_assessment import (
    WaraAssessmentObservationProvider,
    WaraObservationError,
    WaraObservationReceipt,
    WaraReadPlan,
)

from .enablement import control_enablement
from .enablement import validate_enablement_profile as validate_wara_enablement_profile
from .models import (
    WaraApplicabilityStatus,
    WaraAssessmentRequest,
    WaraAssessmentResult,
    WaraControlResult,
    WaraEvaluationStatus,
    WaraEvidenceReceipt,
    WaraSatisfactionStatus,
    WaraScopedResource,
)


class WaraAssessmentRuntime:
    """Evaluate the conservative crosswalk without I/O or execution authority."""

    def __init__(
        self,
        catalog: WaraAssessmentCatalog,
        evaluator_bindings: WaraEvaluatorBindingCatalog | None = None,
        rule_bindings: WaraRuleBindingCatalog | None = None,
    ) -> None:
        if evaluator_bindings is not None and (
            evaluator_bindings.source_revision != catalog.source_revision
            or evaluator_bindings.crosswalk_digest != catalog.crosswalk_digest
        ):
            raise ValueError("WARA evaluator bindings do not match the assessment catalog")
        if rule_bindings is not None:
            if (
                rule_bindings.source_revision != catalog.source_revision
                or rule_bindings.crosswalk_digest != catalog.crosswalk_digest
            ):
                raise ValueError("WARA Rule bindings do not match the assessment catalog")
            query_bound = {
                binding.aprl_guid
                for binding in (evaluator_bindings.bindings if evaluator_bindings else ())
            }
            if query_bound & {binding.aprl_guid for binding in rule_bindings.bindings}:
                raise ValueError("a WARA recommendation MUST have one evaluator binding kind")
        self._catalog = catalog
        self._evaluator_bindings = evaluator_bindings
        self._rule_bindings = rule_bindings

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
        expected_rule_digest = (
            self._rule_bindings.overlay_digest if self._rule_bindings is not None else None
        )
        if request.rule_bindings_digest != expected_rule_digest:
            raise ValueError("WARA assessment Rule bindings digest mismatch")
        self.validate_enablement_profile(request)
        evidence_by_id = _index_evidence(request.evidence)
        controls = tuple(
            replace(
                self._evaluate_control(record, request, evidence_by_id.get(record.aprl_guid, ())),
                enablement=control_enablement(record, request),
            )
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
        if request.rule_bindings_digest is not None:
            digest_material["rule_bindings_digest"] = request.rule_bindings_digest
        if request.enablement_profile is not None:
            digest_material["enablement_profile"] = request.enablement_profile.model_dump(
                mode="json"
            )
        return WaraAssessmentResult(
            **material,
            evaluator_bindings_digest=request.evaluator_bindings_digest,
            result_digest=canonical_digest(digest_material),
            rule_bindings_digest=request.rule_bindings_digest,
            enablement_profile=request.enablement_profile,
        )

    def validate_enablement_profile(self, request: WaraAssessmentRequest) -> None:
        validate_wara_enablement_profile(self._catalog, request)

    def _evaluate_control(
        self,
        record: WaraRecommendationCrosswalk,
        request: WaraAssessmentRequest,
        evidence: tuple[WaraEvidenceReceipt, ...],
    ) -> WaraControlResult:
        if not control_enablement(record, request).enabled:
            return WaraControlResult(
                recommendation_id=record.aprl_guid,
                catalog_state="active",
                mapping_state=record.mapping_state.value,
                applicability=WaraApplicabilityStatus.UNKNOWN,
                evaluation=WaraEvaluationStatus.NOT_EVALUATED,
                satisfaction=WaraSatisfactionStatus.UNKNOWN,
                evidence_refs=(),
                evidence_digests=(),
                evidence_complete=False,
                limitations=("control_disabled",),
            )
        limitations: list[str] = []
        binding = _binding_for(record, self._evaluator_bindings)
        rule_binding = _rule_binding_for(record, self._rule_bindings)
        evaluator_ref, blocked_reasons = _resolved_query_evaluator(record, binding)
        if rule_binding is not None:
            # A reviewed exact Rule binding replaces the missing query evaluator; the query is
            # never executed for this recommendation.
            evaluator_ref = rule_binding.evaluator_ref
            blocked_reasons = tuple(
                reason for reason in blocked_reasons if reason != "missing_exact_evaluator"
            )
        matching = _matching_resources(record, request)
        canonical_mapping = _canonical_mapping_is_admitted(record)
        if not canonical_mapping:
            limitations.append("unsupported_resource_type")
        if not matching:
            limitations.append("scope_not_observed")
        query_admitted = (
            not blocked_reasons
            if rule_binding is not None
            else _query_is_admitted(record, binding, evaluator_ref, blocked_reasons)
        )
        admitted = tuple(
            receipt
            for receipt in evidence
            if _receipt_admitted(
                receipt,
                request,
                record,
                evaluator_ref=evaluator_ref,
                rule_bound=rule_binding is not None,
                automatic_admitted=query_admitted,
            )
        )
        manual_fallback = record.automation_available and any(
            receipt.evidence_kind not in {"provider_observation", "rule"} for receipt in admitted
        )
        if manual_fallback:
            limitations.append("manual_evidence_fallback")
        query_blocked = (
            record.disposition is WaraDisposition.AMBIGUOUS_OR_BLOCKED and not query_admitted
        )
        if query_blocked:
            limitations.append(
                "automatic_evaluation_unavailable" if manual_fallback else "crosswalk_blocked"
            )
            if record.query_review is not None:
                limitations.extend(blocked_reasons)
        applicability = (
            WaraApplicabilityStatus.APPLICABLE
            if matching and canonical_mapping
            else WaraApplicabilityStatus.UNKNOWN
        )
        if query_blocked and not manual_fallback:
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
        if len(outcomes) > 1:
            limitations.append("evidence_conflict")
            satisfaction = WaraSatisfactionStatus.UNKNOWN
            evaluation = WaraEvaluationStatus.NOT_EVALUATED
        elif outcomes == {WaraSatisfactionStatus.NOT_APPLICABLE}:
            applicability = WaraApplicabilityStatus.NOT_APPLICABLE
            satisfaction = WaraSatisfactionStatus.NOT_APPLICABLE
            evaluation = WaraEvaluationStatus.EVALUATED
        elif outcomes == {WaraSatisfactionStatus.SATISFIED}:
            satisfaction = WaraSatisfactionStatus.SATISFIED
            evaluation = WaraEvaluationStatus.EVALUATED
        elif WaraSatisfactionStatus.FAILED in outcomes:
            satisfaction = WaraSatisfactionStatus.FAILED
            evaluation = WaraEvaluationStatus.EVALUATED
        else:
            satisfaction = WaraSatisfactionStatus.UNKNOWN
            evaluation = WaraEvaluationStatus.EVALUATED
        return _control_result(
            record,
            applicability,
            evaluation,
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

        self._runtime.validate_enablement_profile(request)
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
            if not control_enablement(record, request).enabled:
                continue
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
        or not _canonical_mapping_is_admitted(record)
        or review.safety_classification is not QuerySafetyClassification.READ_ONLY_BOUNDED
        or evaluator_ref is None
        or blocked_reasons
        or not _query_is_admitted(record, binding, evaluator_ref, blocked_reasons)
    ):
        raise ValueError("WARA recommendation has no admitted read-only query")
    resources = _matching_resources(record, request)
    if not resources:
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
        resource_ids=tuple(sorted(resource.resource_id for resource in resources)),
        provider_resource_types=tuple(
            sorted({resource.provider_resource_type.casefold() for resource in resources})
        ),
        inventory_generation=request.inventory_generation,
        maximum_rows=review.maximum_rows,
        timeout_seconds=review.timeout_seconds,
        evidence_freshness_ceiling_seconds=(review.evidence_freshness_ceiling_seconds),
    )


def _canonical_mapping_is_admitted(record: WaraRecommendationCrosswalk) -> bool:
    mapping = record.applicability
    candidates = mapping.canonical_resource_types or (
        (mapping.canonical_resource_type,) if mapping.canonical_resource_type is not None else ()
    )
    return mapping.disposition is ResourceTypeDisposition.CANONICAL and bool(candidates)


def _matching_resources(
    record: WaraRecommendationCrosswalk,
    request: WaraAssessmentRequest,
) -> tuple[WaraScopedResource, ...]:
    """Match only exact targets already bound into the authorized observed scope."""

    mapping = record.applicability
    subscription_scoped = (
        mapping.normalized_provider_type
        in {"microsoft.subscription/subscriptions", "microsoft.resources/subscriptions"}
        or "microsoft.resources/subscriptions" in mapping.provider_resource_types
    )
    provider_types = mapping.provider_resource_types or (
        ("microsoft.resources/subscriptions",)
        if subscription_scoped
        else (mapping.normalized_provider_type,)
    )
    matching = []
    for resource in request.resources:
        if resource.provider_resource_type.casefold() not in provider_types:
            continue
        if not set(record.workload_tags).issubset(resource.workload_tags):
            continue
        # A workload child never proves a subscription target or complete subscription scope.
        if subscription_scoped:
            if resource.provider_resource_type.casefold() != "microsoft.resources/subscriptions":
                continue
            if (
                re.fullmatch(
                    r"/subscriptions/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                    resource.resource_id,
                    flags=re.IGNORECASE,
                )
                is None
            ):
                continue
        matching.append(resource)
    return tuple(matching)


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


def _rule_binding_for(
    record: WaraRecommendationCrosswalk,
    rule_bindings: WaraRuleBindingCatalog | None,
) -> WaraRuleBinding | None:
    review = record.query_review
    if rule_bindings is None or review is None:
        return None
    return rule_bindings.resolve(record.aprl_guid, review.body_digest)


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
    automatic_admitted: bool,
    rule_bound: bool = False,
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
    if receipt.evidence_kind not in {"provider_observation", "rule"}:
        requirement = record.manual_evidence
        if (
            requirement is None
            or requirement.blocked_reason is not None
            or receipt.evidence_kind != requirement.kind
            or receipt.producer != requirement.authoritative_producer
            or receipt.freshness_ceiling_seconds != requirement.freshness_ceiling_seconds
        ):
            return False
        freshness_ceiling_seconds = requirement.freshness_ceiling_seconds
    else:
        review = record.query_review
        if not automatic_admitted or review is None or evaluator_ref is None:
            return False
        if (
            receipt.evidence_kind != ("rule" if rule_bound else "provider_observation")
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
