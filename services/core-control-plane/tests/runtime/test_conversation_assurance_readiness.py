from __future__ import annotations

import json

import pytest
from fdai.core.conversation.semantic_current_evidence import (
    SemanticCurrentEvidenceObservation,
)
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError
from fdai.runtime.conversation_assurance_readiness import (
    ReadinessStage,
    RuntimeCapabilityReadiness,
    RuntimeReadinessInventory,
    assess_capability_readiness,
    observe_runtime_readiness,
    write_runtime_readiness_receipt,
)
from fdai_service_contracts.ontology_query import EvidenceAuthority

_PRINCIPAL = Principal(id="watchdog-local", role=Role.CONTRIBUTOR)
_PRINCIPAL_SCOPE_DIGEST = semantic_principal_scope_digest(
    principal=_PRINCIPAL,
    purpose="operations-review",
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


class _Probe:
    def __init__(
        self,
        observations: dict[str, SemanticCurrentEvidenceObservation],
    ) -> None:
        self.observations = observations
        self.calls: list[tuple[str, Principal]] = []

    async def observe(
        self,
        *,
        function_name: str,
        principal: Principal,
    ) -> SemanticCurrentEvidenceObservation:
        self.calls.append((function_name, principal))
        return self.observations[function_name]


class _UnauthorizedProbe:
    async def observe(
        self,
        *,
        function_name: str,
        principal: Principal,
    ) -> SemanticCurrentEvidenceObservation:
        del function_name, principal
        raise PermissionError("not authorized")


def _observation(
    function_name: str,
    authority: EvidenceAuthority,
    *,
    complete: bool = True,
    principal_scope_digest: str = _PRINCIPAL_SCOPE_DIGEST,
    incomplete_reason: str | None = None,
) -> SemanticCurrentEvidenceObservation:
    return SemanticCurrentEvidenceObservation(
        function_name=function_name,
        complete=complete,
        authority=authority,
        principal_scope_digest=principal_scope_digest,
        incomplete_reason=incomplete_reason,
    )


@pytest.mark.asyncio
async def test_runtime_observation_uses_bound_provider_evidence_and_authority() -> None:
    probe = _Probe(
        {
            "query.resource_health_inventory": _observation(
                "query.resource_health_inventory",
                EvidenceAuthority.SERVER_RESOURCE_HEALTH,
            ),
            "query.resource_state_inventory": _observation(
                "query.resource_state_inventory",
                EvidenceAuthority.SERVER_INVENTORY_GRAPH,
            ),
            "query.subscription_service_health": _observation(
                "query.subscription_service_health",
                EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
            ),
        }
    )

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
        current_evidence_probe=probe,
        principal=_PRINCIPAL,
    )

    assert probe.calls == [
        ("query.resource_health_inventory", _PRINCIPAL),
        ("query.resource_state_inventory", _PRINCIPAL),
        ("query.subscription_service_health", _PRINCIPAL),
    ]
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
    assert resource_health.evidence_ready
    assert resource_health.provided_authority == "server_resource_health"
    resource_state = inventory.capability("query.resource_state_inventory")
    assert resource_state is not None
    assert resource_state.evidence_ready
    assert resource_state.provided_authority == "server_inventory_graph"


@pytest.mark.asyncio
async def test_runtime_observation_classifies_provider_authority_failure_as_unavailable() -> None:
    inventory = await observe_runtime_readiness(
        declared_function_names=("query.subscription_service_health",),
        function_bindings={
            "query.subscription_service_health": "server_subscription_health",
        },
        current_evidence_probe=_UnauthorizedProbe(),
        principal=_PRINCIPAL,
    )

    service_health = inventory.capability("query.subscription_service_health")
    assert service_health is not None
    assert service_health.bound
    assert not service_health.reachable
    assert not service_health.evidence_ready
    assert service_health.unavailable_reason == "authority_or_source_unavailable"


@pytest.mark.asyncio
async def test_runtime_observation_preserves_function_incomplete_reason() -> None:
    probe = _Probe(
        {
            "query.resource_state_inventory": _observation(
                "query.resource_state_inventory",
                EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                complete=False,
                incomplete_reason="resource_state_evidence_incomplete",
            )
        }
    )

    inventory = await observe_runtime_readiness(
        declared_function_names=("query.resource_state_inventory",),
        function_bindings={"query.resource_state_inventory": "server_inventory_graph"},
        current_evidence_probe=probe,
        principal=_PRINCIPAL,
    )

    resource_state = inventory.capability("query.resource_state_inventory")
    assert resource_state is not None
    assert resource_state.reachable
    assert not resource_state.evidence_ready
    assert resource_state.unavailable_reason == "resource_state_evidence_incomplete"


@pytest.mark.asyncio
async def test_runtime_observation_preserves_bounded_query_hold_reason() -> None:
    class HeldProbe:
        async def observe(
            self,
            *,
            function_name: str,
            principal: Principal,
        ) -> SemanticCurrentEvidenceObservation:
            del function_name, principal
            raise QueryNodeHeldError("graph_refresh_hold:graph_stale,source_incomplete")

    inventory = await observe_runtime_readiness(
        declared_function_names=("query.resource_state_inventory",),
        function_bindings={"query.resource_state_inventory": "server_inventory_graph"},
        current_evidence_probe=HeldProbe(),
        principal=_PRINCIPAL,
    )

    resource_state = inventory.capability("query.resource_state_inventory")
    assert resource_state is not None
    assert resource_state.bound
    assert resource_state.reachable
    assert not resource_state.evidence_ready
    assert resource_state.provided_authority == "server_inventory_graph"
    assert resource_state.unavailable_reason == ("graph_refresh_hold:graph_stale,source_incomplete")


@pytest.mark.asyncio
async def test_unbound_current_evidence_function_is_not_probed() -> None:
    probe = _Probe({})

    inventory = await observe_runtime_readiness(
        declared_function_names=("query.subscription_service_health",),
        function_bindings={},
        current_evidence_probe=probe,
        principal=_PRINCIPAL,
    )

    service_health = inventory.capability("query.subscription_service_health")
    assert probe.calls == []
    assert service_health is not None
    assert not service_health.bound
    assert service_health.unavailable_reason == "runtime_binding_unavailable"


@pytest.mark.asyncio
async def test_unbound_schema_function_is_not_evidence_ready() -> None:
    inventory = await observe_runtime_readiness(
        declared_function_names=("query.manifest",),
        function_bindings={},
        current_evidence_probe=None,
        principal=_PRINCIPAL,
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
            current_evidence_probe=None,
            principal=_PRINCIPAL,
        )


@pytest.mark.asyncio
async def test_incomplete_current_evidence_is_reachable_but_not_ready() -> None:
    function_name = "query.resource_state_inventory"
    inventory = await observe_runtime_readiness(
        declared_function_names=(function_name,),
        function_bindings={function_name: "server_inventory_graph"},
        current_evidence_probe=_Probe(
            {
                function_name: _observation(
                    function_name,
                    EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                    complete=False,
                )
            }
        ),
        principal=_PRINCIPAL,
    )

    state = inventory.capability(function_name)
    assert state is not None
    assert state.reachable
    assert not state.evidence_ready
    assert state.provided_authority == "server_inventory_graph"
    assert state.unavailable_reason == "current_evidence_incomplete"


@pytest.mark.asyncio
async def test_current_evidence_for_another_principal_scope_is_not_ready() -> None:
    function_name = "query.resource_health_inventory"
    inventory = await observe_runtime_readiness(
        declared_function_names=(function_name,),
        function_bindings={function_name: "server_resource_health"},
        current_evidence_probe=_Probe(
            {
                function_name: _observation(
                    function_name,
                    EvidenceAuthority.SERVER_RESOURCE_HEALTH,
                    principal_scope_digest="sha256:" + ("a" * 64),
                )
            }
        ),
        principal=_PRINCIPAL,
    )

    health = inventory.capability(function_name)
    assert health is not None
    assert health.reachable
    assert not health.evidence_ready
    assert health.unavailable_reason == "principal_scope_mismatch"


@pytest.mark.asyncio
async def test_probe_authority_must_match_the_exact_runtime_binding() -> None:
    function_name = "query.subscription_service_health"
    inventory = await observe_runtime_readiness(
        declared_function_names=(function_name,),
        function_bindings={function_name: "server_inventory_graph"},
        current_evidence_probe=_Probe(
            {
                function_name: _observation(
                    function_name,
                    EvidenceAuthority.SERVER_SUBSCRIPTION_HEALTH,
                )
            }
        ),
        principal=_PRINCIPAL,
    )

    service_health = inventory.capability(function_name)
    assert service_health is not None
    assert service_health.reachable
    assert not service_health.evidence_ready
    assert service_health.provided_authority == "server_subscription_health"
    assert service_health.unavailable_reason == "runtime_authority_mismatch"


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
