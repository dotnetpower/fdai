"""Executed-action observation runtime binding tests."""

from __future__ import annotations

import base64

import httpx
import pytest
from fdai.composition import default_container
from fdai.delivery.azure.observation_context import build_azure_observation_context_pair
from fdai.delivery.azure.vm_power_state import (
    AzureSubscriptionVmPowerStateSource,
    AzureVmPowerStateReading,
)
from fdai.delivery.executed_action_observation import (
    ActionRoutedExecutedActionObservationCollector,
)
from fdai.delivery.reconciliation import IndependentObservationContextVerifier
from fdai.delivery.reconciliation_artifacts import StateStoreReconciliationArtifactResolver
from fdai.runtime.observation_evidence import (
    bind_executed_action_observation_from_env,
    build_vm_power_state_source,
)
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing import InMemoryStateStore

_SEED = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")


def _container():
    config = AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "fdai.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )
    return default_container(config)


def _environment() -> dict[str, str]:
    return {
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_OHL_OBSERVATION_SIGNING_SEED": _SEED,
        "FDAI_OHL_OBSERVER_IDENTITY": "observer:heimdall:azure",
        "FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE": "azure-managed-identity:observer",
        "FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE": "azure-managed-identity:finops",
        "FDAI_OHL_VM_START_EXECUTOR_CREDENTIAL_LINEAGE": ("azure-managed-identity:resilience"),
        "FDAI_OHL_SOURCE_IDENTITY": "source:promoted-azure-inventory",
        "FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE": "azure-managed-identity:inventory",
        "FDAI_OHL_SOURCE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
        "FDAI_OHL_VERIFIER_IDENTITY": "observation-verifier:ohl-ed25519",
    }


class _VmPowerStateSource:
    async def observe(
        self,
        *,
        resource_ref: str,
        target_revision: int,
    ) -> AzureVmPowerStateReading:
        raise AssertionError((resource_ref, target_revision))


class _Identity:
    async def get_token(self, audience: str):
        raise AssertionError(audience)


async def test_builds_vm_source_from_distinct_explicit_identity() -> None:
    calls: list[tuple[str, bool]] = []

    def identity_builder(
        _http_client: httpx.AsyncClient,
        *,
        client_id_env: str,
        require_client_id: bool,
    ):
        calls.append((client_id_env, require_client_id))
        return _Identity()

    async with httpx.AsyncClient() as client:
        source = build_vm_power_state_source(
            subscription_id="00000000-0000-0000-0000-000000000000",
            environ={
                "FDAI_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "FDAI_OHL_SOURCE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000003",
            },
            http_client=client,
            identity_builder=identity_builder,
        )

    assert isinstance(source, AzureSubscriptionVmPowerStateSource)
    assert calls == [("FDAI_OHL_SOURCE_MI_CLIENT_ID", True)]


def test_vm_source_rejects_core_identity_reuse() -> None:
    with pytest.raises(RuntimeError, match="MUST be distinct"):
        build_vm_power_state_source(
            subscription_id="00000000-0000-0000-0000-000000000000",
            environ={
                "FDAI_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "FDAI_OHL_SOURCE_MI_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
            },
            http_client=None,
            identity_builder=lambda *_args, **_kwargs: _Identity(),
        )


def test_absent_configuration_keeps_observation_unavailable() -> None:
    container = _container()

    assert (
        bind_executed_action_observation_from_env(
            container,
            state_store=InMemoryStateStore(),
            environ={},
        )
        is container
    )


def test_partial_configuration_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="configuration is incomplete"):
        bind_executed_action_observation_from_env(
            _container(),
            state_store=InMemoryStateStore(),
            environ={"FDAI_OHL_OBSERVATION_SIGNING_SEED": _SEED},
        )


def test_local_venue_cannot_bind_deployment_signing_key() -> None:
    environment = _environment()
    environment["FDAI_EXECUTION_VENUE"] = "local"

    with pytest.raises(RuntimeError, match="deployed execution venue"):
        bind_executed_action_observation_from_env(
            _container(),
            state_store=InMemoryStateStore(),
            environ=environment,
            vm_power_state_source=_VmPowerStateSource(),
        )


def test_complete_configuration_binds_collector_verifier_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities = []

    async def inventory_context(resource_ref: str):
        del resource_ref
        return None

    def capture_identity_pair(*, private_key_seed, identity):
        identities.append(identity)
        return build_azure_observation_context_pair(
            private_key_seed=private_key_seed,
            identity=identity,
        )

    monkeypatch.setattr(
        "fdai.runtime.observation_evidence._build_inventory_context_provider",
        lambda: inventory_context,
    )
    monkeypatch.setattr(
        "fdai.runtime.observation_evidence.build_azure_observation_context_pair",
        capture_identity_pair,
    )

    bound = bind_executed_action_observation_from_env(
        _container(),
        state_store=InMemoryStateStore(),
        environ=_environment(),
        vm_power_state_source=_VmPowerStateSource(),
    )

    assert isinstance(
        bound.executed_action_observation_collector,
        ActionRoutedExecutedActionObservationCollector,
    )
    assert isinstance(
        bound.reconciliation_observation_verifier,
        IndependentObservationContextVerifier,
    )
    assert isinstance(
        bound.reconciliation_artifact_resolver,
        StateStoreReconciliationArtifactResolver,
    )
    assert [identity.executor_credential_lineage for identity in identities] == [
        "azure-managed-identity:finops",
        "azure-managed-identity:resilience",
    ]


def test_complete_configuration_requires_vm_power_state_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def inventory_context(resource_ref: str):
        del resource_ref
        return None

    monkeypatch.setattr(
        "fdai.runtime.observation_evidence._build_inventory_context_provider",
        lambda: inventory_context,
    )

    with pytest.raises(RuntimeError, match="requires an HTTP client"):
        bind_executed_action_observation_from_env(
            _container(),
            state_store=InMemoryStateStore(),
            environ=_environment(),
        )


def test_complete_configuration_requires_inventory_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.observation_evidence._build_inventory_context_provider",
        lambda: None,
    )

    with pytest.raises(RuntimeError, match="durable inventory evidence"):
        bind_executed_action_observation_from_env(
            _container(),
            state_store=InMemoryStateStore(),
            environ=_environment(),
        )


def test_complete_configuration_rejects_collapsed_known_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def inventory_context(resource_ref: str):
        del resource_ref
        return None

    monkeypatch.setattr(
        "fdai.runtime.observation_evidence._build_inventory_context_provider",
        lambda: inventory_context,
    )
    environment = _environment()
    environment["FDAI_OHL_SOURCE_IDENTITY"] = environment["FDAI_OHL_OBSERVER_IDENTITY"]

    with pytest.raises(RuntimeError, match="identities MUST be distinct"):
        bind_executed_action_observation_from_env(
            _container(),
            state_store=InMemoryStateStore(),
            environ=environment,
            vm_power_state_source=_VmPowerStateSource(),
        )
