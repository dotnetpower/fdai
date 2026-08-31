"""Strict runtime binding for executed-action observation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai.composition import Container
from fdai.delivery.azure.executed_action_observation import (
    AzureScaleOutObservationCollector,
)
from fdai.delivery.azure.observation_context import (
    AzureObservationContextIdentity,
    build_azure_observation_context_pair,
)
from fdai.delivery.azure.operational_evidence import AzureCachedOperationalSnapshotSource
from fdai.delivery.reconciliation import IndependentObservationContextVerifier
from fdai.delivery.reconciliation_artifacts import StateStoreReconciliationArtifactResolver
from fdai.runtime.providers import _build_inventory_context_provider
from fdai.runtime.venue import VenueCapability, resolve_execution_venue, select_capability
from fdai.shared.providers.state_store import StateStore

_CONFIG_ENV = (
    "FDAI_OHL_OBSERVATION_SIGNING_SEED",
    "FDAI_OHL_OBSERVER_IDENTITY",
    "FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE",
    "FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE",
    "FDAI_OHL_SOURCE_IDENTITY",
    "FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE",
    "FDAI_OHL_VERIFIER_IDENTITY",
)


def bind_executed_action_observation_from_env(
    container: Container,
    *,
    state_store: StateStore,
    environ: Mapping[str, str],
) -> Container:
    """Bind the OHL collector only from one complete deployed identity set."""

    values = {name: environ.get(name, "").strip() for name in _CONFIG_ENV}
    configured = {name for name, value in values.items() if value}
    if not configured:
        return container
    missing = set(_CONFIG_ENV) - configured
    if missing:
        raise RuntimeError(
            "OHL observation context configuration is incomplete: " + ", ".join(sorted(missing))
        )
    venue = resolve_execution_venue(environ)
    if select_capability(VenueCapability.WORKLOAD_IDENTITY_SOURCE, venue) != "managed_identity":
        raise RuntimeError("OHL observation context requires the deployed execution venue")
    inventory_context = _build_inventory_context_provider()
    if inventory_context is None:
        raise RuntimeError("OHL observation context requires durable inventory evidence")
    _require_distinct(
        "OHL observation identities",
        values["FDAI_OHL_OBSERVER_IDENTITY"],
        values["FDAI_OHL_SOURCE_IDENTITY"],
        values["FDAI_OHL_VERIFIER_IDENTITY"],
    )
    identity = AzureObservationContextIdentity(
        observer_credential_lineage=values["FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE"],
        executor_credential_lineage=values["FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE"],
        source_credential_lineage=values["FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE"],
        verifier_identity=values["FDAI_OHL_VERIFIER_IDENTITY"],
    )
    issuer, authenticator = build_azure_observation_context_pair(
        private_key_seed=values["FDAI_OHL_OBSERVATION_SIGNING_SEED"],
        identity=identity,
    )
    verifier = IndependentObservationContextVerifier(authenticator=authenticator)
    artifacts = StateStoreReconciliationArtifactResolver(store=state_store)
    collector = AzureScaleOutObservationCollector(
        snapshots=AzureCachedOperationalSnapshotSource(inventory_context),
        context_issuer=issuer,
        observer_identity=values["FDAI_OHL_OBSERVER_IDENTITY"],
        source_identity=values["FDAI_OHL_SOURCE_IDENTITY"],
    )
    return replace(
        container,
        reconciliation_artifact_resolver=artifacts,
        reconciliation_observation_verifier=verifier,
        executed_action_observation_collector=collector,
    )


def _require_distinct(label: str, *values: str) -> None:
    if len({value.casefold() for value in values}) != len(values):
        raise RuntimeError(f"{label} MUST be distinct")


__all__ = ["bind_executed_action_observation_from_env"]
