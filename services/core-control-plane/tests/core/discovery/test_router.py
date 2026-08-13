"""Discovery routing, equivalent fallback, and canonical merge tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.discovery.router import (
    BackendEligibility,
    compile_discovery_routes,
    equivalent_fallback,
    merge_discovery_results,
)
from fdai_service_contracts.discovery import (
    DiscoveryCoverageStatus,
    DiscoveryIntent,
    DiscoveryLimits,
    DiscoveryOperationProfile,
    DiscoveryPredicate,
    DiscoveryProfile,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    DiscoveryUniverse,
    discovery_intent_digest,
    discovery_profile_digest,
)
from fdai_service_contracts.discovery_evidence import (
    DiscoveryPlanResult,
    ProviderResourceObservation,
)
from fdai_service_contracts.ontology_query import content_digest

DIGEST = "sha256:" + ("a" * 64)


def _intent() -> DiscoveryIntent:
    predicate = DiscoveryPredicate(field="name", operator="contains", values=("example",))
    values: dict[str, object] = {
        "result_kind": DiscoveryResultKind.LIST,
        "universes": (DiscoveryUniverse.ARM_RESOURCES,),
        "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
        "scope_digest": DIGEST,
        "predicates": (predicate,),
        "limits": DiscoveryLimits(),
        "include_command_explanation": True,
        "unresolved_modifiers": (),
        "execution_authority": False,
    }
    return DiscoveryIntent(intent_digest=discovery_intent_digest(**values), **values)


def _operation(operation_id: str, backend: str, priority: int) -> DiscoveryOperationProfile:
    return DiscoveryOperationProfile(
        operation_id=operation_id,
        backend=backend,
        universes=("arm_resources",),
        result_kinds=("list",),
        scope_kinds=("subscription",),
        predicate_fields=("name",),
        predicate_operators=("contains",),
        projection=("provider_ref", "provider_type", "name"),
        output_schema_id="provider-resource-observation.v1",
        equivalence_key="azure.arm-resources.list.v1",
        identity_profile="azure.reader",
        priority=priority,
        command_template_id="azure.arg.resources.list.v1",
    )


def _profile() -> DiscoveryProfile:
    values: dict[str, object] = {
        "profile_id": "azure.arm-resources",
        "revision": "1.0.0",
        "cloud": "azure",
        "provider_type": "Microsoft.Resources/resources",
        "operations": (
            _operation("azure.inventory.resources.list", "promoted_inventory", 10),
            _operation("azure.arg.resources.list", "resource_graph", 20),
            _operation("azure.arm.resources.list", "generic_arm", 30),
        ),
        "limits": DiscoveryLimits(),
        "provenance_refs": ("microsoft.resource-graph.resources",),
    }
    return DiscoveryProfile(profile_digest=discovery_profile_digest(**values), **values)


def _eligibility(
    operation_id: str,
    *,
    available: bool,
    complete: bool,
    reason: str | None = None,
) -> BackendEligibility:
    intent = _intent()
    return BackendEligibility(
        operation_id=operation_id,
        available=available,
        complete=complete,
        scope_digest=intent.scope_digest,
        predicate_digest=content_digest(
            [predicate.model_dump(mode="json") for predicate in intent.predicates]
        ),
        output_schema_id="provider-resource-observation.v1",
        freshness_seconds=10,
        reason_code=reason,
    )


def test_router_uses_narrowest_complete_backend() -> None:
    decisions = compile_discovery_routes(
        intent=_intent(),
        profile=_profile(),
        authorization_ceiling_digest=DIGEST,
        eligibility=(
            _eligibility("azure.inventory.resources.list", available=True, complete=True),
        ),
    )

    assert decisions[0].status is DiscoveryCoverageStatus.COVERED
    assert decisions[0].plan is not None
    assert decisions[0].plan.backend.value == "promoted_inventory"


def test_router_falls_back_only_with_exact_scope_predicate_and_output() -> None:
    decisions = compile_discovery_routes(
        intent=_intent(),
        profile=_profile(),
        authorization_ceiling_digest=DIGEST,
        eligibility=(
            _eligibility(
                "azure.inventory.resources.list",
                available=False,
                complete=False,
                reason="snapshot_stale",
            ),
            _eligibility("azure.arg.resources.list", available=True, complete=True),
        ),
    )

    decision = decisions[0]
    assert decision.status is DiscoveryCoverageStatus.FALLBACK
    assert decision.plan is not None
    assert decision.plan.backend.value == "resource_graph"
    assert decision.plan.fallback_history[0].reason_code == "snapshot_stale"

    valid = _eligibility("azure.arg.resources.list", available=True, complete=True)
    wrong_scope = BackendEligibility(
        operation_id=valid.operation_id,
        available=True,
        complete=True,
        scope_digest="sha256:" + ("b" * 64),
        predicate_digest=valid.predicate_digest,
        output_schema_id=valid.output_schema_id,
        freshness_seconds=valid.freshness_seconds,
    )
    rejected = compile_discovery_routes(
        intent=_intent(),
        profile=_profile(),
        authorization_ceiling_digest=DIGEST,
        eligibility=(wrong_scope,),
    )
    assert rejected[0].plan is None
    assert rejected[0].status is DiscoveryCoverageStatus.UNSUPPORTED


def test_equivalence_rejects_scope_or_predicate_weakening() -> None:
    primary = compile_discovery_routes(
        intent=_intent(),
        profile=_profile(),
        authorization_ceiling_digest=DIGEST,
        eligibility=(_eligibility("azure.arg.resources.list", available=True, complete=True),),
    )[0].plan
    assert primary is not None
    weakened = primary.model_copy(update={"predicates": ()})

    assert equivalent_fallback(primary, primary)
    assert not equivalent_fallback(primary, weakened)


def test_merge_preserves_unmapped_observation_and_partial_completeness() -> None:
    observation = ProviderResourceObservation(
        provider_ref_digest=DIGEST,
        provider_type="Example.Provider/widgets",
        scope_kind="subscription",
        mapping_status="unmapped",
        evidence_ref="discovery:sha256:example",
    )
    result = DiscoveryPlanResult(
        plan_digest=DIGEST,
        universe="arm_resources",
        backend="resource_graph",
        status="partial",
        complete=False,
        truncated=True,
        observations=(observation,),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        reason_code="page_limit",
    )

    merged = merge_discovery_results((result,))

    assert merged.observations == (observation,)
    assert merged.complete is False
    assert merged.observations[0].semantic_type is None


def test_merge_rejects_conflicting_mapping_for_same_provider_ref() -> None:
    unmapped = ProviderResourceObservation(
        provider_ref_digest=DIGEST,
        provider_type="Example.Provider/widgets",
        scope_kind="subscription",
        mapping_status="unmapped",
        evidence_ref="discovery:sha256:example",
    )
    mapped = unmapped.model_copy(update={"mapping_status": "mapped", "semantic_type": "compute.vm"})
    first = DiscoveryPlanResult(
        plan_digest=DIGEST,
        universe="arm_resources",
        backend="resource_graph",
        status="covered",
        complete=True,
        truncated=False,
        observations=(unmapped,),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = first.model_copy(
        update={"plan_digest": "sha256:" + ("b" * 64), "observations": (mapped,)}
    )

    with pytest.raises(ValueError, match="conflicting provider observations"):
        merge_discovery_results((first, second))
