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
            "query.resource_health_inventory",
            "query.resource_state_inventory",
            "query.subscription_service_health",
        ),
        semantic_runtime_bound=True,
        service_health_reader=reader,
        resource_health_reader_bound=True,
    )

    assert reader.calls == 1
    manifest = inventory.capability("query.manifest")
    assert manifest is not None
    assert manifest.provided_authority == "server_ontology_manifest"
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
        semantic_runtime_bound=True,
        service_health_reader=_UnauthorizedReader(),
        resource_health_reader_bound=False,
    )

    service_health = inventory.capability("query.subscription_service_health")
    assert service_health is not None
    assert service_health.bound
    assert not service_health.reachable
    assert not service_health.evidence_ready
    assert service_health.unavailable_reason == "authority_or_source_unavailable"


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
