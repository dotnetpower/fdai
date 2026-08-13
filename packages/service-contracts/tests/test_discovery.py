"""Bounded provider resource discovery contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryCoverageStatus,
    DiscoveryIntent,
    DiscoveryLimits,
    DiscoveryMappingStatus,
    DiscoveryOperationProfile,
    DiscoveryPredicate,
    DiscoveryPredicateField,
    DiscoveryPredicateOperator,
    DiscoveryProfile,
    DiscoveryQueryPlan,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    DiscoveryUniverse,
    discovery_intent_digest,
    discovery_plan_digest,
    discovery_profile_digest,
)
from fdai_service_contracts.discovery_evidence import (
    DiscoveryPlanResult,
    MergedDiscoveryResult,
    ProviderResourceObservation,
    merged_discovery_result_digest,
)
from pydantic import ValidationError

DIGEST = "sha256:" + ("a" * 64)


def _intent(**overrides: object) -> DiscoveryIntent:
    values: dict[str, object] = {
        "result_kind": DiscoveryResultKind.LIST,
        "universes": (DiscoveryUniverse.ARM_RESOURCES,),
        "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
        "scope_digest": DIGEST,
        "predicates": (
            DiscoveryPredicate(
                field=DiscoveryPredicateField.NAME,
                operator=DiscoveryPredicateOperator.CONTAINS,
                values=("example",),
            ),
        ),
        "limits": DiscoveryLimits(),
        "include_command_explanation": True,
        "unresolved_modifiers": (),
        "execution_authority": False,
    }
    values.update(overrides)
    return DiscoveryIntent(intent_digest=discovery_intent_digest(**values), **values)


def _plan(intent: DiscoveryIntent, **overrides: object) -> DiscoveryQueryPlan:
    values: dict[str, object] = {
        "plan_id": "azure.resources.arg.v1",
        "intent_digest": intent.intent_digest,
        "profile_id": "azure.arm-resources",
        "profile_revision": "1.0.0",
        "universes": intent.universes,
        "backend": DiscoveryBackend.RESOURCE_GRAPH,
        "operation_id": "azure.arg.resources.list",
        "equivalence_key": "azure.arm-resources.list.v1",
        "scope_kind": intent.scope_kind,
        "scope_digest": intent.scope_digest,
        "authorization_ceiling_digest": DIGEST,
        "predicates": intent.predicates,
        "projection": ("provider_ref", "provider_type", "name"),
        "limits": intent.limits,
        "fallback_history": (),
        "output_schema_id": "provider-resource-observation.v1",
        "normalization_id": "azure.provider-resource-observation.v1",
        "validation_versions": ("azure-resource-graph-api@2022-10-01",),
        "execution_authority": False,
    }
    values.update(overrides)
    return DiscoveryQueryPlan(plan_digest=discovery_plan_digest(**values), **values)


def test_intent_and_plan_are_immutable_and_authority_free() -> None:
    intent = _intent()
    plan = _plan(intent)

    assert intent.execution_authority is False
    assert plan.execution_authority is False
    with pytest.raises((FrozenInstanceError, ValidationError)):
        plan.backend = DiscoveryBackend.GENERIC_ARM  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    (
        "example; az account show",
        "example | project id",
        "$(az account get-access-token)",
        "`az group list`",
        "TOKEN=$SECRET",
        "example\nResources",
    ),
)
def test_intent_rejects_executable_predicate_text(value: str) -> None:
    with pytest.raises(ValidationError, match="executable text"):
        DiscoveryPredicate(field="name", operator="contains", values=(value,))


def test_intent_rejects_unresolved_modifiers() -> None:
    with pytest.raises(ValidationError, match="unresolved modifiers"):
        _intent(unresolved_modifiers=("except inaccessible resources",))


@pytest.mark.parametrize("field", ("query", "kql", "argv", "url", "command"))
def test_plan_rejects_every_executable_text_field(field: str) -> None:
    intent = _intent()
    payload = _plan(intent).model_dump(mode="json")
    payload[field] = "az resource list"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DiscoveryQueryPlan.model_validate(payload)


def test_unknown_provider_type_is_preserved_without_semantic_promotion() -> None:
    observation = ProviderResourceObservation(
        provider_ref_digest=DIGEST,
        provider_type="Example.Provider/widgets",
        scope_kind="subscription",
        mapping_status=DiscoveryMappingStatus.UNMAPPED,
        evidence_ref="discovery:sha256:example",
    )

    assert observation.mapping_status is DiscoveryMappingStatus.UNMAPPED
    assert observation.semantic_type is None
    assert observation.provider_type == "Example.Provider/widgets"


def test_unmapped_observation_rejects_semantic_type_and_raw_resource_id() -> None:
    with pytest.raises(ValidationError, match="MUST NOT name a semantic type"):
        ProviderResourceObservation(
            provider_ref_digest=DIGEST,
            provider_type="Example.Provider/widgets",
            scope_kind="subscription",
            mapping_status="unmapped",
            semantic_type="compute.vm",
            evidence_ref="discovery:sha256:example",
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProviderResourceObservation.model_validate(
            {
                "provider_ref_digest": DIGEST,
                "provider_type": "Example.Provider/widgets",
                "scope_kind": "subscription",
                "mapping_status": "unmapped",
                "evidence_ref": "discovery:sha256:example",
                "resource_id": "/subscriptions/hidden/resourceGroups/hidden/providers/Example.Provider/widgets/x",
            }
        )


def test_profile_rejects_executable_fields_and_accepts_registered_metadata() -> None:
    operation = DiscoveryOperationProfile(
        operation_id="azure.arg.resources.list",
        backend="resource_graph",
        universes=("arm_resources",),
        result_kinds=("list", "count", "types"),
        scope_kinds=("subscription", "resource_group"),
        predicate_fields=("name", "provider_type", "resource_group", "location", "tag"),
        predicate_operators=("eq", "contains", "in", "exists"),
        projection=("provider_ref", "provider_type", "name", "resource_group", "location"),
        output_schema_id="provider-resource-observation.v1",
        normalization_id="azure.provider-resource-observation.v1",
        validation_versions=("azure-resource-graph-api@2022-10-01",),
        equivalence_key="azure.arm-resources.list.v1",
        identity_profile="azure.reader",
        priority=20,
        command_template_id="azure.arg.resources.list.v1",
    )
    values: dict[str, object] = {
        "profile_id": "azure.arm-resources",
        "revision": "1.0.0",
        "cloud": "azure",
        "provider_type": "Microsoft.Resources/resources",
        "operations": (operation,),
        "limits": DiscoveryLimits(),
        "provenance_refs": ("microsoft.resource-graph.resources",),
    }
    profile = DiscoveryProfile(
        profile_digest=discovery_profile_digest(**values),
        **values,
    )
    payload = profile.model_dump(mode="json")
    payload["kql"] = "Resources | project id"

    assert profile.operations == (operation,)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DiscoveryProfile.model_validate(payload)


def test_merged_result_cannot_hide_incomplete_plan() -> None:
    observation = ProviderResourceObservation(
        provider_ref_digest=DIGEST,
        provider_type="Example.Provider/widgets",
        scope_kind="subscription",
        mapping_status="unmapped",
        evidence_ref="discovery:sha256:example",
    )
    plan_result = DiscoveryPlanResult(
        plan_digest=DIGEST,
        universe="arm_resources",
        backend="resource_graph",
        status=DiscoveryCoverageStatus.PARTIAL,
        complete=False,
        truncated=True,
        observations=(observation,),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        reason_code="page_limit",
    )
    values: dict[str, object] = {
        "observations": (observation,),
        "plan_results": (plan_result,),
        "complete": False,
        "execution_authority": False,
    }

    merged = MergedDiscoveryResult(
        result_digest=merged_discovery_result_digest(**values),
        **values,
    )

    assert merged.complete is False
    with pytest.raises(ValidationError, match="completeness does not match"):
        MergedDiscoveryResult(
            result_digest=merged_discovery_result_digest(**{**values, "complete": True}),
            **{**values, "complete": True},
        )
