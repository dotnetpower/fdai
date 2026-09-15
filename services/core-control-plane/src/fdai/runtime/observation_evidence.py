"""Strict runtime binding for executed-action observation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai.composition import Container
from fdai.core.ontology_platform import ExecutedActionObservationCollector
from fdai.delivery.azure.executed_action_observation import (
    AzureScaleOutObservationCollector,
)
from fdai.delivery.azure.observation_context import (
    AzureObservationContextIdentity,
    build_azure_observation_context_pair,
)
from fdai.delivery.azure.operational_evidence import AzureCachedOperationalSnapshotSource
from fdai.delivery.azure.vm_power_state import AzureVmPowerStateSource
from fdai.delivery.azure.vm_power_state_observation import AzureVmStartObservationCollector
from fdai.delivery.executed_action_observation import (
    ActionRoutedExecutedActionObservationCollector,
)
from fdai.delivery.reconciliation import IndependentObservationContextVerifier
from fdai.delivery.reconciliation_artifacts import StateStoreReconciliationArtifactResolver
from fdai.runtime.providers import _build_inventory_context_provider
from fdai.runtime.venue import VenueCapability, resolve_execution_venue, select_capability
from fdai.shared.providers.state_store import StateStore

_OBSERVED_ACTION_TYPES = frozenset({"ops.scale-out", "ops.start-vm"})
_VM_POWER_STATE_SOURCE_IDENTITY = "source:azure-arm-vm-instance-view"
_CONFIG_ENV = (
    "FDAI_OHL_OBSERVATION_SIGNING_SEED",
    "FDAI_OHL_OBSERVER_IDENTITY",
    "FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE",
    "FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE",
    "FDAI_OHL_VM_START_EXECUTOR_CREDENTIAL_LINEAGE",
    "FDAI_OHL_SOURCE_IDENTITY",
    "FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE",
    "FDAI_OHL_SOURCE_MI_CLIENT_ID",
    "FDAI_OHL_VERIFIER_IDENTITY",
)


def bind_executed_action_observation_from_env(
    container: Container,
    *,
    state_store: StateStore,
    environ: Mapping[str, str],
    vm_power_state_source: AzureVmPowerStateSource | None = None,
) -> Container:
    """Bind routed Azure collectors only from one complete deployed identity set."""

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
    if vm_power_state_source is None:
        raise RuntimeError("OHL observation context requires a VM power-state source")
    _require_distinct(
        "OHL observation identities",
        values["FDAI_OHL_OBSERVER_IDENTITY"],
        values["FDAI_OHL_SOURCE_IDENTITY"],
        values["FDAI_OHL_VERIFIER_IDENTITY"],
    )
    _require_distinct(
        "OHL VM-start observation identities",
        values["FDAI_OHL_OBSERVER_IDENTITY"],
        _VM_POWER_STATE_SOURCE_IDENTITY,
        values["FDAI_OHL_VERIFIER_IDENTITY"],
    )
    _require_distinct(
        "OHL action executor credential lineages",
        values["FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE"],
        values["FDAI_OHL_VM_START_EXECUTOR_CREDENTIAL_LINEAGE"],
    )
    scale_out_identity = AzureObservationContextIdentity(
        observer_credential_lineage=values["FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE"],
        executor_credential_lineage=values["FDAI_OHL_EXECUTOR_CREDENTIAL_LINEAGE"],
        source_credential_lineage=values["FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE"],
        verifier_identity=values["FDAI_OHL_VERIFIER_IDENTITY"],
    )
    scale_out_issuer, authenticator = build_azure_observation_context_pair(
        private_key_seed=values["FDAI_OHL_OBSERVATION_SIGNING_SEED"],
        identity=scale_out_identity,
    )
    vm_start_issuer, _ = build_azure_observation_context_pair(
        private_key_seed=values["FDAI_OHL_OBSERVATION_SIGNING_SEED"],
        identity=AzureObservationContextIdentity(
            observer_credential_lineage=values["FDAI_OHL_OBSERVER_CREDENTIAL_LINEAGE"],
            executor_credential_lineage=values["FDAI_OHL_VM_START_EXECUTOR_CREDENTIAL_LINEAGE"],
            source_credential_lineage=values["FDAI_OHL_SOURCE_CREDENTIAL_LINEAGE"],
            verifier_identity=values["FDAI_OHL_VERIFIER_IDENTITY"],
        ),
    )
    verifier = IndependentObservationContextVerifier(authenticator=authenticator)
    artifacts = StateStoreReconciliationArtifactResolver(store=state_store)
    collectors: dict[str, ExecutedActionObservationCollector] = {
        "ops.scale-out": AzureScaleOutObservationCollector(
            snapshots=AzureCachedOperationalSnapshotSource(inventory_context),
            context_issuer=scale_out_issuer,
            observer_identity=values["FDAI_OHL_OBSERVER_IDENTITY"],
            source_identity=values["FDAI_OHL_SOURCE_IDENTITY"],
        ),
        "ops.start-vm": AzureVmStartObservationCollector(
            source=vm_power_state_source,
            context_issuer=vm_start_issuer,
            observer_identity=values["FDAI_OHL_OBSERVER_IDENTITY"],
            source_identity=_VM_POWER_STATE_SOURCE_IDENTITY,
        ),
    }
    if frozenset(collectors) != _OBSERVED_ACTION_TYPES:  # pragma: no cover - source invariant
        raise RuntimeError("executed Action observation routes do not match their manifest")
    collector = ActionRoutedExecutedActionObservationCollector(collectors)
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
