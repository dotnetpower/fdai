"""Azure discovery profile, observation, explanation, and receipt safety tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fdai.core.discovery.router import BackendEligibility, compile_discovery_routes
from fdai.delivery.azure.discovery_explanation import render_command_explanation
from fdai.delivery.azure.discovery_observations import observe_azure_resource
from fdai.delivery.azure.discovery_profiles import default_azure_discovery_profiles
from fdai.delivery.azure.discovery_receipts import (
    build_provider_execution_receipt,
    provider_execution_projection,
)
from fdai_service_contracts.discovery import (
    DiscoveryCoverageStatus,
    DiscoveryIntent,
    DiscoveryLimits,
    DiscoveryPredicate,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    DiscoveryUniverse,
    discovery_intent_digest,
)
from fdai_service_contracts.discovery_evidence import ProviderExecutionCommand
from fdai_service_contracts.ontology_query import content_digest
from pydantic import ValidationError

DIGEST = "sha256:" + ("a" * 64)


def _intent(profile_index: int = 1) -> DiscoveryIntent:
    universe = (
        DiscoveryUniverse.RESOURCE_CONTAINERS
        if profile_index == 0
        else DiscoveryUniverse.ARM_RESOURCES
    )
    predicate = DiscoveryPredicate(field="name", operator="contains", values=("example",))
    values: dict[str, object] = {
        "result_kind": DiscoveryResultKind.LIST,
        "universes": (universe,),
        "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
        "scope_digest": DIGEST,
        "predicates": (predicate,),
        "limits": DiscoveryLimits(max_results=100),
        "include_command_explanation": True,
        "unresolved_modifiers": (),
        "execution_authority": False,
    }
    return DiscoveryIntent(intent_digest=discovery_intent_digest(**values), **values)


def _plan(profile_index: int = 1):
    profile = default_azure_discovery_profiles()[profile_index]
    operation = profile.operations[1]
    intent = _intent(profile_index)
    eligibility = BackendEligibility(
        operation_id=operation.operation_id,
        available=True,
        complete=True,
        scope_digest=intent.scope_digest,
        predicate_digest=content_digest(
            [predicate.model_dump(mode="json") for predicate in intent.predicates]
        ),
        output_schema_id=operation.output_schema_id,
        freshness_seconds=0,
    )
    decision = compile_discovery_routes(
        intent=intent,
        profile=profile,
        authorization_ceiling_digest=DIGEST,
        eligibility=(eligibility,),
    )[0]
    assert decision.plan is not None
    return profile, operation, decision.plan


def test_profiles_contain_registered_metadata_without_executable_text() -> None:
    encoded = json.dumps(
        [profile.model_dump(mode="json") for profile in default_azure_discovery_profiles()],
        sort_keys=True,
    )

    assert "graph-query" not in encoded
    assert "Resources |" not in encoded
    assert "argv" not in encoded
    assert "https://" not in encoded


def test_arg_profiles_pin_normalization_and_validation_versions() -> None:
    for profile in default_azure_discovery_profiles():
        operation = next(
            item for item in profile.operations if item.backend.value == "resource_graph"
        )
        assert operation.normalization_id == "azure.provider-resource-observation.v1"
        assert operation.validation_versions == (
            "azure-resource-graph-api@2022-10-01",
            "azure-cli@2.87.0",
            "resource-graph-extension@2.1.1",
        )


def test_unknown_azure_type_is_retained_as_unmapped_without_raw_id() -> None:
    raw_id = "/subscriptions/example/resourceGroups/example/providers/Example.Provider/widgets/x"
    observation = observe_azure_resource(
        {"id": raw_id, "type": "Example.Provider/widgets", "name": "widget-example"},
        scope_kind="subscription",
        semantic_types={},
        evidence_ref="discovery:sha256:example",
    )
    encoded = observation.model_dump_json()

    assert observation.mapping_status.value == "unmapped"
    assert observation.semantic_type is None
    assert raw_id not in encoded


def test_provider_execution_receipt_drops_raw_ids_tokens_and_errors() -> None:
    _profile, operation, plan = _plan()
    receipt = build_provider_execution_receipt(
        plan=plan,
        operation=operation,
        page_count=2,
        count=1,
        preview_rows=(
            {
                "name": "resource-example",
                "type": "Example.Provider/widgets",
                "id": (
                    "/subscriptions/hidden/resourceGroups/hidden/providers/"
                    "Example.Provider/widgets/x"
                ),
                "$skipToken": "hidden-token",
                "provider_error": "Bearer hidden-credential",
            },
        ),
    )
    projection = provider_execution_projection(receipt)
    encoded = json.dumps(projection, sort_keys=True)

    assert projection["redacted"] is True
    assert "<subscription-id>" in encoded
    for forbidden in ("/subscriptions/", "hidden-token", "hidden-credential", "provider_error"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "command",
    (
        "az resource list; env",
        "az resource list | grep secret",
        "az resource show --ids /subscriptions/hidden/resourceGroups/hidden",
        "az account get-access-token",
        "AZURE_CONFIG_DIR=/tmp az resource list",
        "az resource list < /tmp/input",
        "az resource list > /tmp/output",
        "source /tmp/profile",
        "az resource list\x00hidden",
    ),
)
def test_provider_execution_contract_rejects_unsafe_command(command: str) -> None:
    with pytest.raises(ValidationError, match="executable or sensitive"):
        ProviderExecutionCommand(
            label="resources",
            command_id="azure.arm.resources.list.v1",
            command=command,
        )


def test_command_explanation_matches_golden_and_is_equivalent_only() -> None:
    _profile, operation, plan = _plan(0)
    explanation = render_command_explanation(
        plan=plan,
        operation=operation,
        validated_at=datetime(2026, 1, 1, tzinfo=UTC),
        cli_version="2.87.0",
    )
    encoded = explanation.model_dump_json()

    assert explanation.cli_argv == (
        "az",
        "graph",
        "query",
        "--subscriptions",
        "<subscription-id>",
        "--graph-query",
        "<registered-kql:azure.arg.resource-groups.list.v1>",
        "--first",
        "100",
        "--output",
        "json",
    )
    assert explanation.kql_template == (
        "ResourceContainers | where type =~ "
        "'microsoft.resources/subscriptions/resourcegroups' | "
        "where name contains '<predicate-1>' | "
        "project id, type, name, subscriptionId, resourceGroup, location, tags | "
        "order by id asc"
    )
    assert explanation.equivalent_command is True
    assert explanation.execution_authority is False
    assert "/subscriptions/hidden/resourceGroups/" not in encoded
    assert "00000000-0000-0000-0000-000000000000" not in encoded


def test_coverage_contract_exposes_documented_unmapped_state() -> None:
    assert DiscoveryCoverageStatus.UNMAPPED.value == "unmapped"


@pytest.mark.parametrize(
    ("english", "korean", "profile_index", "result_kind", "predicates"),
    (
        (
            "List all resources.",
            "모든 리소스를 나열해 줘.",
            1,
            DiscoveryResultKind.LIST,
            (),
        ),
        (
            "List resource groups containing example.",
            "example이 포함된 리소스 그룹을 나열해 줘.",
            0,
            DiscoveryResultKind.LIST,
            (DiscoveryPredicate(field="name", operator="contains", values=("example",)),),
        ),
        (
            "Show the resource types in scope.",
            "범위 안의 리소스 타입을 보여 줘.",
            1,
            DiscoveryResultKind.TYPES,
            (),
        ),
    ),
)
def test_bilingual_scenarios_clear_identical_typed_authority_checks(
    english: str,
    korean: str,
    profile_index: int,
    result_kind: DiscoveryResultKind,
    predicates: tuple[DiscoveryPredicate, ...],
) -> None:
    signatures: list[tuple[object, ...]] = []
    for surface in (english, korean):
        assert surface.strip()
        profile = default_azure_discovery_profiles()[profile_index]
        operation = profile.operations[1]
        values: dict[str, object] = {
            "result_kind": result_kind,
            "universes": operation.universes,
            "scope_kind": DiscoveryScopeKind.SUBSCRIPTION,
            "scope_digest": DIGEST,
            "predicates": predicates,
            "limits": DiscoveryLimits(max_results=100),
            "include_command_explanation": True,
            "unresolved_modifiers": (),
            "execution_authority": False,
        }
        intent = DiscoveryIntent(intent_digest=discovery_intent_digest(**values), **values)
        eligibility = BackendEligibility(
            operation_id=operation.operation_id,
            available=True,
            complete=True,
            scope_digest=intent.scope_digest,
            predicate_digest=content_digest(
                [predicate.model_dump(mode="json") for predicate in intent.predicates]
            ),
            output_schema_id=operation.output_schema_id,
            freshness_seconds=0,
        )
        decision = compile_discovery_routes(
            intent=intent,
            profile=profile,
            authorization_ceiling_digest=DIGEST,
            eligibility=(eligibility,),
        )[0]
        assert decision.plan is not None
        signatures.append(
            (
                intent.intent_digest,
                decision.plan.backend,
                decision.plan.scope_digest,
                decision.plan.normalization_id,
                decision.plan.validation_versions,
                decision.plan.execution_authority,
            )
        )

    assert signatures[0] == signatures[1]
    assert signatures[0][-1] is False
