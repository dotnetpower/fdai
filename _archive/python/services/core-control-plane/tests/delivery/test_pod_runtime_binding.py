"""Executable production composition with no live credentials or provider requests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.investigation import KubernetesPodLifecycleAnalyzer, StaticPodLifecycleEvidenceSource
from fdai.core.investigation.kubernetes_pod_status import PodFailureEvidence
from fdai.delivery import pod_runtime_binding as binding_module
from fdai.delivery.aks_subscription_discovery import AksCachedSubscriptionBinding
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.kubernetes_api_inventory import (
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_pod_evidence import LivePodLifecycleEvidenceSource
from fdai.delivery.kubernetes_pod_observations import PodEvidenceUnavailableError
from fdai.delivery.pod_evidence_binding import POD_EVIDENCE_ENV
from fdai.delivery.pod_recovery import PodRecoveryAnalyzer
from fdai.delivery.pod_runtime_binding import build_production_pod_analyzer
from fdai.shared.providers.inventory import PromotedInventoryGeneration, ResourceRecord

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
ARM_CLUSTER = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example"
    "/providers/Microsoft.ContainerService/managedClusters/aks-example"
)
NEUTRAL_CLUSTER = to_neutral_id(ARM_CLUSTER)


def _environment() -> dict[str, str]:
    return {
        "FDAI_INVENTORY_DSN": "postgresql://localhost:5433/fdai_validation",
        "FDAI_INVENTORY_SCOPES": SUBSCRIPTION,
        "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example.com",
        "FDAI_KUBERNETES_CLUSTER_REF": ARM_CLUSTER,
        "FDAI_KUBERNETES_CA_PATH": "config/example-public-ca.pem",
        "FDAI_KUBERNETES_TOKEN_PATH": "config/example-token-reference",
    }


def _discovery_environment() -> dict[str, str]:
    return {
        "FDAI_INVENTORY_DSN": "postgresql://localhost:5433/fdai_validation",
        "FDAI_INVENTORY_SCOPES": SUBSCRIPTION,
        "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "true",
    }


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    request = AsyncMock(side_effect=AssertionError("No provider requests are permitted"))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    monkeypatch.setattr(
        binding_module.ssl,
        "create_default_context",
        lambda **_: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )
    return request


async def test_service_account_factory_constructs_source_without_io_and_owns_clients(
    no_network: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory_read = AsyncMock(side_effect=AssertionError("Factory MUST NOT read inventory"))
    token_read = AsyncMock(side_effect=AssertionError("Factory MUST NOT load tokens"))
    monkeypatch.setattr(
        binding_module.PostgresPromotedInventoryGenerationReader,
        "load_active_generation",
        inventory_read,
    )
    monkeypatch.setattr(ServiceAccountTokenAuth, "headers", token_read)
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, environ=_environment())
        assert binding.unavailable_reason is None
        assert isinstance(binding.analyzer, PodRecoveryAnalyzer)
        source = binding.analyzer._analyzer._source
        assert isinstance(source, LivePodLifecycleEvidenceSource)
        collector = source._collectors[NEUTRAL_CLUSTER]
        assert collector._config.cluster_ref == NEUTRAL_CLUSTER
        assert isinstance(collector._auth, ServiceAccountTokenAuth)
        assert source._lifecycle_cluster_refs == {NEUTRAL_CLUSTER: ARM_CLUSTER}
        assert not collector._http.is_closed
    assert collector._http.is_closed
    inventory_read.assert_not_awaited()
    token_read.assert_not_awaited()
    no_network.assert_not_awaited()


async def test_static_replay_precedes_invalid_production_configuration(
    monkeypatch: pytest.MonkeyPatch, no_network: AsyncMock
) -> None:
    replay = KubernetesPodLifecycleAnalyzer(StaticPodLifecycleEvidenceSource(()))
    monkeypatch.setattr(binding_module, "build_pod_analyzer", lambda _: replay)
    monkeypatch.setattr(
        binding_module.InventoryJobConfig,
        "from_env",
        lambda *_: pytest.fail("Replay MUST NOT parse production configuration"),
    )
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(
            stack=stack,
            environ={POD_EVIDENCE_ENV: "[explicit-replay]", "FDAI_INVENTORY_SCOPES": "invalid"},
        )
    assert binding.analyzer is replay
    assert binding.unavailable_reason is None
    no_network.assert_not_awaited()


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        ({}, "inventory_dsn_unbound"),
        (
            {
                "FDAI_INVENTORY_DSN": "postgresql://localhost:5433/fdai_validation",
                "FDAI_INVENTORY_SCOPES": SUBSCRIPTION,
            },
            "kubernetes_source_unbound",
        ),
        (
            {
                "FDAI_INVENTORY_DSN": "postgresql://localhost:5433/fdai_validation",
                "FDAI_INVENTORY_SCOPES": SUBSCRIPTION,
                "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example.com",
            },
            "kubernetes_source_configuration_invalid",
        ),
    ],
)
async def test_unbound_or_invalid_configuration_is_not_an_empty_healthy_analyzer(
    environment: dict[str, str], reason: str, no_network: AsyncMock
) -> None:
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, environ=environment)
    assert binding.analyzer is None
    assert binding.unavailable_reason == reason
    no_network.assert_not_awaited()


async def test_existing_cli_dsn_can_supply_the_inventory_parser(no_network: AsyncMock) -> None:
    environment = _environment()
    dsn = environment.pop("FDAI_INVENTORY_DSN")
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, dsn=dsn, environ=environment)
    assert binding.analyzer is not None and binding.unavailable_reason is None


async def test_explicit_bindings_cannot_escape_inventory_subscription(
    no_network: AsyncMock,
) -> None:
    environment = _environment()
    environment["FDAI_INVENTORY_SCOPES"] = "synthetic-other-subscription"
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, environ=environment)
    assert binding.analyzer is None
    assert binding.unavailable_reason == "kubernetes_cluster_outside_inventory_scope"
    no_network.assert_not_awaited()


async def test_workload_identity_is_borrowed_and_not_invoked_by_factory(
    no_network: AsyncMock,
) -> None:
    environment = _environment()
    environment.pop("FDAI_KUBERNETES_TOKEN_PATH")
    environment["FDAI_KUBERNETES_AUTH_MODE"] = "workload-identity"
    environment["FDAI_KUBERNETES_AUDIENCE"] = "api://example/.default"
    identity = SimpleNamespace(
        get_token=AsyncMock(side_effect=AssertionError("Factory MUST NOT fetch a token")),
        aclose=AsyncMock(),
    )
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(
            stack=stack, identity=identity, environ=environment
        )
        assert isinstance(binding.analyzer, PodRecoveryAnalyzer)
        collector = binding.analyzer._analyzer._source._collectors[NEUTRAL_CLUSTER]
        assert isinstance(collector._auth, WorkloadIdentityKubernetesAuth)
    identity.get_token.assert_not_awaited()
    identity.aclose.assert_not_awaited()


async def test_workload_identity_is_explicitly_unavailable_when_not_supplied(
    no_network: AsyncMock,
) -> None:
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, environ=_discovery_environment())
    assert binding.analyzer is None
    assert binding.unavailable_reason == "kubernetes_workload_identity_unbound"


async def test_discovery_cache_is_owned_by_stack_and_not_read_during_factory(
    no_network: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_store = SimpleNamespace(
        read_state=AsyncMock(side_effect=AssertionError("Factory MUST NOT read cache state")),
        aclose=AsyncMock(),
    )
    inventory_read = AsyncMock(side_effect=AssertionError("Factory MUST NOT read inventory"))
    monkeypatch.setattr(binding_module, "PostgresStateStore", lambda **_: cache_store)
    monkeypatch.setattr(
        binding_module.PostgresPromotedInventoryGenerationReader,
        "load_active_generation",
        inventory_read,
    )
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(
            stack=stack, identity=SimpleNamespace(), environ=_discovery_environment()
        )
        assert binding.analyzer is not None
        cache_store.aclose.assert_not_awaited()
    cache_store.read_state.assert_not_awaited()
    inventory_read.assert_not_awaited()
    cache_store.aclose.assert_awaited_once()


async def test_fleet_json_reuses_existing_parser_and_rejects_duplicate_bindings(
    no_network: AsyncMock,
) -> None:
    environment = {
        "FDAI_INVENTORY_DSN": "postgresql://localhost:5433/fdai_validation",
        "FDAI_INVENTORY_SCOPES": SUBSCRIPTION,
    }
    entry = {
        "cluster_ref": ARM_CLUSTER,
        "api_server": "https://kubernetes.example.com",
        "auth_mode": "service-account",
        "ca_path": "config/example-public-ca.pem",
        "token_path": "config/example-token-reference",
    }
    environment["FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON"] = json.dumps([entry])
    async with AsyncExitStack() as stack:
        binding = await build_production_pod_analyzer(stack=stack, environ=environment)
        assert isinstance(binding.analyzer, PodRecoveryAnalyzer)
    environment["FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON"] = json.dumps([entry, entry])
    async with AsyncExitStack() as stack:
        duplicate = await build_production_pod_analyzer(stack=stack, environ=environment)
    assert duplicate.analyzer is None
    assert duplicate.unavailable_reason == "kubernetes_source_configuration_invalid"


def _generation() -> PromotedInventoryGeneration:
    return PromotedInventoryGeneration(
        generation="inventory-example",
        complete=True,
        recorded_at=datetime.now(UTC),
        resources=(
            ResourceRecord(
                resource_id=NEUTRAL_CLUSTER,
                type="kubernetes-cluster",
                provider_ref=ARM_CLUSTER,
            ),
            ResourceRecord(
                resource_id="pod:example",
                type="kubernetes.pod",
                props={"cluster_ref": NEUTRAL_CLUSTER},
            ),
        ),
    )


def _cached() -> AksCachedSubscriptionBinding:
    ca = "PUBLIC-CA-EXAMPLE"
    return AksCachedSubscriptionBinding(
        cluster_ref=ARM_CLUSTER,
        api_server="https://kubernetes.example.com",
        audience="api://example/.default",
        ca_pem=ca,
        ca_digest="sha256:" + hashlib.sha256(ca.encode()).hexdigest(),
        observed_at=datetime.now(UTC),
        binding_revision="binding-example",
    )


async def _cached_source(stack: AsyncExitStack) -> Any:
    binding = await build_production_pod_analyzer(
        stack=stack, identity=SimpleNamespace(), environ=_discovery_environment()
    )
    assert isinstance(binding.analyzer, PodRecoveryAnalyzer)
    source = binding.analyzer._analyzer._source
    source._inventory = SimpleNamespace(
        load_active_generation=AsyncMock(return_value=_generation())
    )
    source._cache = SimpleNamespace(read=AsyncMock(return_value=_cached()))
    return source


async def test_subscription_discovery_reads_only_exact_existing_cache_at_observation_time(
    no_network: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_sources = []

    async def observe(source: Any, **_: Any) -> PodFailureEvidence:
        observed_sources.append(source)
        return PodFailureEvidence(None, None)

    monkeypatch.setattr(LivePodLifecycleEvidenceSource, "observe_pod", observe)
    async with AsyncExitStack() as stack:
        source = await _cached_source(stack)
        source._cache.read.assert_not_awaited()
        source._inventory.load_active_generation.assert_not_awaited()
        evidence = await source.observe_pod(resource_ref="pod:example", window_seconds=60)
        assert evidence == PodFailureEvidence(None, None)
        source._cache.read.assert_awaited_once_with(ARM_CLUSTER)
        collector = observed_sources[0]._collectors[NEUTRAL_CLUSTER]
        assert observed_sources[0]._lifecycle_cluster_refs == {NEUTRAL_CLUSTER: ARM_CLUSTER}
        assert not collector._http.is_closed
    assert collector._http.is_closed
    no_network.assert_not_awaited()


async def test_discovered_two_pods_share_one_pinned_cluster_source(
    no_network: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = []

    async def observe(source: Any, **_: Any) -> PodFailureEvidence:
        sources.append(source)
        await asyncio.sleep(0)
        return PodFailureEvidence(None, None)

    monkeypatch.setattr(LivePodLifecycleEvidenceSource, "observe_pod", observe)
    async with AsyncExitStack() as stack:
        source = await _cached_source(stack)
        generation = _generation()
        second = replace(generation.resources[1], resource_id="pod:second")
        source._inventory.load_active_generation.return_value = replace(
            generation, resources=(*generation.resources, second)
        )
        await asyncio.gather(
            source.observe_pod(resource_ref="pod:example", window_seconds=60),
            source.observe_pod(resource_ref="pod:second", window_seconds=60),
        )
        source._cache.read.assert_awaited_once_with(ARM_CLUSTER)
        source._inventory.load_active_generation.assert_awaited_once()
        assert len(sources) == 2 and sources[0] is sources[1]
        collector = sources[0]._collectors[NEUTRAL_CLUSTER]
        assert not collector._http.is_closed
    assert collector._http.is_closed
    no_network.assert_not_awaited()


@pytest.mark.parametrize("cache_state", ["missing", "stale", "foreign"])
async def test_cached_binding_cannot_manufacture_availability(
    cache_state: str, no_network: AsyncMock
) -> None:
    async with AsyncExitStack() as stack:
        source = await _cached_source(stack)
        cached = _cached()
        if cache_state == "missing":
            cached = None
        elif cache_state == "stale":
            cached = replace(cached, observed_at=datetime.now(UTC) - timedelta(days=30))
        else:
            cached = replace(cached, cluster_ref=ARM_CLUSTER.replace("aks-example", "aks-foreign"))
        source._cache.read.return_value = cached
        with pytest.raises(PodEvidenceUnavailableError) as raised:
            await source.observe_pod(resource_ref="pod:example", window_seconds=60)
    assert (
        raised.value.reason
        == {
            "missing": "kubernetes_binding_cache_unavailable",
            "stale": "kubernetes_binding_cache_stale",
            "foreign": "kubernetes_binding_cache_conflict",
        }[cache_state]
    )
    no_network.assert_not_awaited()
