from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from fdai.runtime.conversation_assurance_readiness import (
    ReadinessStage,
    RuntimeCapabilityReadiness,
    RuntimeReadinessInventory,
    assess_capability_readiness,
    observe_runtime_readiness,
    write_runtime_readiness_receipt,
)


def test_declaration_without_runtime_binding_is_unavailable() -> None:
    result = assess_capability_readiness(
        capability_id="service-outage",
        enabled=True,
        required_functions=("query.subscription_service_health",),
        expected_authority="server_subscription_health",
        inventory=RuntimeReadinessInventory(
            capabilities=(
                RuntimeCapabilityReadiness(
                    function_name="query.subscription_service_health",
                    declared=True,
                    bound=False,
                    reachable=False,
                    evidence_ready=False,
                    unavailable_reason="provider_unbound",
                ),
            )
        ),
    )

    assert result.stage is ReadinessStage.DECLARED
    assert not result.selectable
    assert result.unavailable_reason == "provider_unbound"


def test_reachable_provider_without_authority_is_unavailable() -> None:
    result = assess_capability_readiness(
        capability_id="service-outage",
        enabled=True,
        required_functions=("query.subscription_service_health",),
        expected_authority="server_subscription_health",
        inventory=RuntimeReadinessInventory(
            capabilities=(
                RuntimeCapabilityReadiness(
                    function_name="query.subscription_service_health",
                    declared=True,
                    bound=True,
                    reachable=True,
                    evidence_ready=False,
                    unavailable_reason="authority_unavailable",
                ),
            )
        ),
    )

    assert result.stage is ReadinessStage.REACHABLE
    assert not result.selectable
    assert result.unavailable_reason == "authority_unavailable"


def test_only_evidence_ready_matching_authority_is_selectable() -> None:
    result = assess_capability_readiness(
        capability_id="service-outage",
        enabled=True,
        required_functions=("query.subscription_service_health",),
        expected_authority="server_subscription_health",
        inventory=RuntimeReadinessInventory(
            capabilities=(
                RuntimeCapabilityReadiness(
                    function_name="query.subscription_service_health",
                    declared=True,
                    bound=True,
                    reachable=True,
                    evidence_ready=True,
                    provided_authority="server_subscription_health",
                ),
            )
        ),
    )

    assert result.stage is ReadinessStage.EVIDENCE_READY
    assert result.selectable


def test_multi_source_capability_requires_the_exact_authority_set() -> None:
    result = assess_capability_readiness(
        capability_id="resource-state",
        enabled=True,
        required_functions=(
            "query.resource_state_inventory",
            "query.resource_health_inventory",
        ),
        expected_authority="multiple_authoritative_sources",
        expected_authorities=("server_inventory_graph", "server_resource_health"),
        inventory=RuntimeReadinessInventory(
            capabilities=(
                RuntimeCapabilityReadiness(
                    function_name="query.resource_state_inventory",
                    declared=True,
                    bound=True,
                    reachable=True,
                    evidence_ready=True,
                    provided_authority="server_inventory_graph",
                ),
                RuntimeCapabilityReadiness(
                    function_name="query.resource_health_inventory",
                    declared=True,
                    bound=True,
                    reachable=True,
                    evidence_ready=True,
                    provided_authority="server_resource_health",
                ),
            )
        ),
    )

    assert result.selectable
    assert result.provided_authority == "multiple_authoritative_sources"
    assert result.provided_authorities == (
        "server_inventory_graph",
        "server_resource_health",
    )


def test_multi_source_readiness_rejects_stale_terminal_authority_descriptor() -> None:
    with pytest.raises(ValueError, match="descriptor does not match"):
        assess_capability_readiness(
            capability_id="resource-state",
            enabled=True,
            required_functions=(
                "query.resource_state_inventory",
                "query.resource_health_inventory",
            ),
            expected_authority="server_subscription_health",
            expected_authorities=("server_inventory_graph", "server_resource_health"),
            inventory=RuntimeReadinessInventory(capabilities=()),
        )


def test_evidence_ready_with_wrong_authority_is_unavailable() -> None:
    result = assess_capability_readiness(
        capability_id="service-outage",
        enabled=True,
        required_functions=("query.subscription_service_health",),
        expected_authority="server_subscription_health",
        inventory=RuntimeReadinessInventory(
            capabilities=(
                RuntimeCapabilityReadiness(
                    function_name="query.subscription_service_health",
                    declared=True,
                    bound=True,
                    reachable=True,
                    evidence_ready=True,
                    provided_authority="server_inventory_graph",
                ),
            )
        ),
    )

    assert result.stage is ReadinessStage.EVIDENCE_READY
    assert not result.selectable
    assert result.unavailable_reason == "authority_mismatch"


def test_readiness_stages_cannot_skip_prerequisites() -> None:
    with pytest.raises(ValueError, match="MUST be bound"):
        RuntimeCapabilityReadiness(
            function_name="query.subscription_service_health",
            declared=True,
            bound=False,
            reachable=True,
            evidence_ready=False,
            unavailable_reason="invalid",
        )


@dataclass(frozen=True)
class _Collection:
    complete: bool


class _Reader:
    def __init__(self, *, complete: bool) -> None:
        self.complete = complete
        self.calls = 0

    async def read_active(self) -> _Collection:
        self.calls += 1
        return _Collection(complete=self.complete)


class _UnauthorizedReader:
    async def read_active(self) -> _Collection:
        raise PermissionError("not authorized")


@pytest.mark.asyncio
async def test_runtime_observation_uses_bound_provider_evidence_and_authority() -> None:
    reader = _Reader(complete=True)

    inventory = await observe_runtime_readiness(
        declared_function_names=(
            "query.manifest",
            "query.ontology_declaration",
            "query.ontology_relationships",
            "query.resource_health_inventory",
            "query.resource_state_inventory",
            "query.subscription_service_health",
        ),
        function_bindings={
            "query.manifest": "server_ontology_manifest",
            "query.ontology_declaration": "server_ontology_manifest",
            "query.ontology_relationships": "server_ontology_manifest",
            "query.resource_health_inventory": "server_resource_health",
            "query.resource_state_inventory": "server_inventory_graph",
            "query.subscription_service_health": "server_subscription_health",
        },
        service_health_reader=reader,
    )

    assert reader.calls == 1
    manifest = inventory.capability("query.manifest")
    assert manifest is not None
    assert manifest.provided_authority == "server_ontology_manifest"
    for function_name in ("query.ontology_declaration", "query.ontology_relationships"):
        schema_function = inventory.capability(function_name)
        assert schema_function is not None
        assert schema_function.evidence_ready
        assert schema_function.provided_authority == "server_ontology_manifest"
    service_health = inventory.capability("query.subscription_service_health")
    assert service_health is not None
    assert service_health.evidence_ready
    assert service_health.provided_authority == "server_subscription_health"
    resource_health = inventory.capability("query.resource_health_inventory")
    assert resource_health is not None
    assert resource_health.bound
    assert not resource_health.evidence_ready


@pytest.mark.asyncio
async def test_runtime_observation_classifies_provider_authority_failure_as_unavailable() -> None:
    inventory = await observe_runtime_readiness(
        declared_function_names=("query.subscription_service_health",),
        function_bindings={
            "query.subscription_service_health": "server_subscription_health",
        },
        service_health_reader=_UnauthorizedReader(),
    )

    service_health = inventory.capability("query.subscription_service_health")
    assert service_health is not None
    assert service_health.bound
    assert not service_health.reachable
    assert not service_health.evidence_ready
    assert service_health.unavailable_reason == "authority_or_source_unavailable"


@pytest.mark.asyncio
async def test_unbound_service_health_reader_is_not_probed() -> None:
    reader = _Reader(complete=True)

    inventory = await observe_runtime_readiness(
        declared_function_names=("query.subscription_service_health",),
        function_bindings={},
        service_health_reader=reader,
    )

    service_health = inventory.capability("query.subscription_service_health")
    assert reader.calls == 0
    assert service_health is not None
    assert not service_health.bound
    assert service_health.unavailable_reason == "runtime_binding_unavailable"


@pytest.mark.asyncio
async def test_unbound_schema_function_is_not_evidence_ready() -> None:
    inventory = await observe_runtime_readiness(
        declared_function_names=("query.manifest",),
        function_bindings={},
        service_health_reader=None,
    )

    manifest = inventory.capability("query.manifest")
    assert manifest is not None
    assert not manifest.bound
    assert not manifest.reachable
    assert not manifest.evidence_ready
    assert manifest.provided_authority is None
    assert manifest.unavailable_reason == "runtime_binding_unavailable"


@pytest.mark.asyncio
async def test_runtime_observation_rejects_binding_outside_active_release() -> None:
    with pytest.raises(ValueError, match="absent from the active release"):
        await observe_runtime_readiness(
            declared_function_names=("query.manifest",),
            function_bindings={
                "inventory.select_resources": "server_inventory_graph",
            },
            service_health_reader=None,
        )


def test_private_receipt_round_trips_without_positive_defaults(tmp_path) -> None:
    path = tmp_path / "readiness.json"
    inventory = RuntimeReadinessInventory(
        capabilities=(
            RuntimeCapabilityReadiness(
                function_name="query.manifest",
                declared=True,
                bound=True,
                reachable=True,
                evidence_ready=True,
                provided_authority="server_ontology_manifest",
            ),
        )
    )

    write_runtime_readiness_receipt(path, inventory)

    assert (
        RuntimeReadinessInventory.from_dict(json.loads(path.read_text(encoding="utf-8")))
        == inventory
    )
    assert path.stat().st_mode & 0o777 == 0o600
