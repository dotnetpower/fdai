"""Pure backend selection and canonical merge for bounded resource discovery."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.discovery import (
    DiscoveryCoverageStatus,
    DiscoveryFallback,
    DiscoveryIntent,
    DiscoveryOperationProfile,
    DiscoveryProfile,
    DiscoveryQueryPlan,
    DiscoveryUniverse,
    discovery_plan_digest,
)
from fdai_service_contracts.discovery_evidence import (
    DiscoveryPlanResult,
    MergedDiscoveryResult,
    ProviderResourceObservation,
    merged_discovery_result_digest,
)
from fdai_service_contracts.ontology_query import content_digest


@dataclass(frozen=True, slots=True)
class BackendEligibility:
    """Runtime proof that one registered operation preserves the verified intent."""

    operation_id: str
    available: bool
    complete: bool
    scope_digest: str
    predicate_digest: str
    output_schema_id: str
    freshness_seconds: int
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.available and self.reason_code is not None:
            raise ValueError("available backend eligibility MUST NOT include a reason")
        if not self.available and self.reason_code is None:
            raise ValueError("unavailable backend eligibility MUST include a reason")
        if self.freshness_seconds < 0:
            raise ValueError("backend freshness MUST NOT be negative")


@dataclass(frozen=True, slots=True)
class DiscoveryRoutingDecision:
    """One explicit selected plan or unsupported universe outcome."""

    universe: DiscoveryUniverse
    plan: DiscoveryQueryPlan | None
    status: DiscoveryCoverageStatus
    reason_code: str | None = None


def compile_discovery_routes(
    *,
    intent: DiscoveryIntent,
    profile: DiscoveryProfile,
    authorization_ceiling_digest: str,
    eligibility: tuple[BackendEligibility, ...],
) -> tuple[DiscoveryRoutingDecision, ...]:
    """Select one exact-equivalent registered plan per requested universe."""

    by_operation = {item.operation_id: item for item in eligibility}
    if len(by_operation) != len(eligibility):
        raise ValueError("backend eligibility operation ids MUST be unique")
    predicate_digest = content_digest(
        [predicate.model_dump(mode="json") for predicate in intent.predicates]
    )
    decisions: list[DiscoveryRoutingDecision] = []
    for universe in intent.universes:
        operations = sorted(
            (
                operation
                for operation in profile.operations
                if _operation_supports(intent, universe=universe, operation=operation)
            ),
            key=lambda operation: (operation.priority, operation.operation_id),
        )
        fallback_history: list[DiscoveryFallback] = []
        selected: tuple[DiscoveryOperationProfile, bool] | None = None
        partial: DiscoveryOperationProfile | None = None
        for operation in operations:
            runtime = by_operation.get(operation.operation_id)
            reason = _ineligibility_reason(
                intent=intent,
                operation=operation,
                runtime=runtime,
                predicate_digest=predicate_digest,
            )
            if reason is not None:
                _append_fallback(fallback_history, operation=operation, reason=reason)
                continue
            if runtime is None:
                raise RuntimeError("eligible discovery operation lacks runtime evidence")
            if runtime.complete:
                selected = (operation, True)
                break
            partial = partial or operation
            _append_fallback(
                fallback_history,
                operation=operation,
                reason="incomplete_source",
            )
        if selected is None and partial is not None:
            selected = (partial, False)
            fallback_history = [
                item for item in fallback_history if item.backend is not partial.backend
            ]
        if selected is None:
            decisions.append(
                DiscoveryRoutingDecision(
                    universe=universe,
                    plan=None,
                    status=DiscoveryCoverageStatus.UNSUPPORTED,
                    reason_code="no_equivalent_registered_backend",
                )
            )
            continue
        operation, expected_complete = selected
        plan_values: dict[str, object] = {
            "plan_id": f"{profile.profile_id}.{universe.value}",
            "intent_digest": intent.intent_digest,
            "profile_id": profile.profile_id,
            "profile_revision": profile.revision,
            "universes": (universe,),
            "backend": operation.backend,
            "operation_id": operation.operation_id,
            "equivalence_key": operation.equivalence_key,
            "scope_kind": intent.scope_kind,
            "scope_digest": intent.scope_digest,
            "authorization_ceiling_digest": authorization_ceiling_digest,
            "predicates": intent.predicates,
            "projection": operation.projection,
            "limits": intent.limits,
            "fallback_history": tuple(fallback_history),
            "output_schema_id": operation.output_schema_id,
            "normalization_id": operation.normalization_id,
            "validation_versions": operation.validation_versions,
            "execution_authority": False,
        }
        plan = DiscoveryQueryPlan.model_validate(
            {"plan_digest": discovery_plan_digest(**plan_values), **plan_values}
        )
        decisions.append(
            DiscoveryRoutingDecision(
                universe=universe,
                plan=plan,
                status=(
                    DiscoveryCoverageStatus.FALLBACK
                    if expected_complete and fallback_history
                    else DiscoveryCoverageStatus.COVERED
                    if expected_complete
                    else DiscoveryCoverageStatus.PARTIAL
                ),
                reason_code=None if expected_complete else "incomplete_source",
            )
        )
    return tuple(decisions)


def equivalent_fallback(primary: DiscoveryQueryPlan, candidate: DiscoveryQueryPlan) -> bool:
    """Return whether two plans preserve the same scope, predicate, and output contract."""

    return (
        primary.intent_digest == candidate.intent_digest
        and primary.universes == candidate.universes
        and primary.equivalence_key == candidate.equivalence_key
        and primary.scope_kind is candidate.scope_kind
        and primary.scope_digest == candidate.scope_digest
        and primary.authorization_ceiling_digest == candidate.authorization_ceiling_digest
        and primary.predicates == candidate.predicates
        and primary.projection == candidate.projection
        and primary.limits == candidate.limits
        and primary.output_schema_id == candidate.output_schema_id
        and primary.normalization_id == candidate.normalization_id
    )


def merge_discovery_results(results: tuple[DiscoveryPlanResult, ...]) -> MergedDiscoveryResult:
    """Merge exact provider observations while preserving every plan receipt."""

    if not results:
        raise ValueError("discovery merge requires at least one plan result")
    by_ref: dict[str, ProviderResourceObservation] = {}
    by_plan: set[str] = set()
    for result in results:
        if result.plan_digest in by_plan:
            raise ValueError("discovery merge MUST NOT repeat a plan result")
        by_plan.add(result.plan_digest)
        for observation in result.observations:
            existing = by_ref.get(observation.provider_ref_digest)
            if existing is not None and existing != observation:
                raise ValueError("conflicting provider observations MUST NOT be merged")
            by_ref[observation.provider_ref_digest] = observation
    observations = tuple(by_ref[key] for key in sorted(by_ref))
    complete = all(result.complete and not result.truncated for result in results)
    values: dict[str, object] = {
        "observations": observations,
        "plan_results": results,
        "complete": complete,
        "execution_authority": False,
    }
    return MergedDiscoveryResult.model_validate(
        {"result_digest": merged_discovery_result_digest(**values), **values}
    )


def _operation_supports(
    intent: DiscoveryIntent,
    *,
    universe: DiscoveryUniverse,
    operation: DiscoveryOperationProfile,
) -> bool:
    fields = {predicate.field for predicate in intent.predicates}
    operators = {predicate.operator for predicate in intent.predicates}
    return (
        universe in operation.universes
        and intent.result_kind in operation.result_kinds
        and intent.scope_kind in operation.scope_kinds
        and fields <= set(operation.predicate_fields)
        and operators <= set(operation.predicate_operators)
    )


def _ineligibility_reason(
    *,
    intent: DiscoveryIntent,
    operation: DiscoveryOperationProfile,
    runtime: BackendEligibility | None,
    predicate_digest: str,
) -> str | None:
    if runtime is None:
        return "eligibility_unavailable"
    if not runtime.available:
        return runtime.reason_code
    if runtime.scope_digest != intent.scope_digest:
        return "scope_mismatch"
    if runtime.predicate_digest != predicate_digest:
        return "predicate_mismatch"
    if runtime.output_schema_id != operation.output_schema_id:
        return "output_schema_mismatch"
    if runtime.freshness_seconds > intent.limits.freshness_seconds:
        return "freshness_exceeded"
    return None


def _append_fallback(
    history: list[DiscoveryFallback],
    *,
    operation: DiscoveryOperationProfile,
    reason: str,
) -> None:
    if operation.backend not in {item.backend for item in history}:
        history.append(DiscoveryFallback(backend=operation.backend, reason_code=reason))
