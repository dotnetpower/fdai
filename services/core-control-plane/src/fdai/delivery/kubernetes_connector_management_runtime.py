"""Deployment-owned signing of Azure management and ownership constraint evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentContext,
    ObserverDeploymentFact,
    ObserverPreflightReceipt,
)

from fdai.delivery.kubernetes_connector_azure_preflight import (
    AzureManagementPreflight,
    ManagementReader,
)
from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput
from fdai.delivery.kubernetes_connector_management_reader import AzCliManagementReader
from fdai.delivery.kubernetes_connector_preflight import verify_preflight
from fdai.delivery.kubernetes_connector_preflight_runtime import (
    FileObserverPreflightGrants,
    ObserverReadPreflightConfig,
    ObserverSigningConfig,
    _unique,
)
from fdai.delivery.kubernetes_connector_runtime import private_file


class ObserverAzurePreflightConfig(ObserverSigningConfig):
    """One AKS resource id, the gateway origin to classify, and the deployment's method policy."""

    cluster_id: str
    gateway_origin: str
    run_command_profile_allows: bool


class ObserverOwnershipPreflightConfig(ObserverReadPreflightConfig):
    installation_inputs_path: Path


async def collect_azure_preflight(
    path: Path,
    *,
    now: Callable[[], datetime],
    reader: ManagementReader | None = None,
) -> ObserverPreflightReceipt:
    """Sign ARM-derived policy, Run Command, and route facts under one verifier grant."""
    config = ObserverAzurePreflightConfig.model_validate(_load(path))
    facts = await AzureManagementPreflight(
        cluster_id=config.cluster_id,
        reader=reader or AzCliManagementReader(),
        gateway_origin=config.gateway_origin,
        run_command_profile_allows=config.run_command_profile_allows,
        now=now,
    ).collect()
    if config.target_ref != _target(facts):
        raise ValueError("Azure preflight target differs from its binding")
    return await _sign(config, facts, now=now)


async def collect_ownership_preflight(
    path: Path, *, now: Callable[[], datetime]
) -> ObserverPreflightReceipt:
    """Sign whether any foreign owner holds the observer namespace or workload name."""
    from fdai.delivery.kubernetes_api_inventory import ServiceAccountTokenAuth
    from fdai.delivery.kubernetes_connector_ownership_preflight import (
        KubernetesObserverOwnershipPreflight,
    )

    config = ObserverOwnershipPreflightConfig.model_validate(_load(path))
    inputs = ObserverInstallationInput.model_validate(
        json.loads(
            await asyncio.to_thread(private_file, config.installation_inputs_path),
            object_pairs_hook=_unique,
        )
    )
    fact = await KubernetesObserverOwnershipPreflight(
        origin=config.api_origin,
        target_ref=config.target_ref,
        namespace_uid=config.namespace_uid,
        auth=ServiceAccountTokenAuth(config.api_token_path),
        tls=ssl.create_default_context(cafile=str(config.api_ca_path)),
        now=now,
    ).collect_ownership(inputs)
    return await _sign(config, (fact,), now=now)


def _load(path: Path) -> object:
    return json.loads(private_file(path), object_pairs_hook=_unique)


def _target(facts: Sequence[ObserverDeploymentFact]) -> str:
    return facts[0].target_ref


async def _sign(
    config: ObserverSigningConfig,
    facts: Sequence[ObserverDeploymentFact],
    *,
    now: Callable[[], datetime],
) -> ObserverPreflightReceipt:
    private = load_pem_private_key(
        await asyncio.to_thread(private_file, config.signing_key_path), None
    )
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("observer preflight requires an Ed25519 signing key")
    key_ref = "sha256:" + hashlib.sha256(private.public_key().public_bytes_raw()).hexdigest()
    grants = FileObserverPreflightGrants(config.grants_path)
    grant = await grants.read(config.target_ref, config.issuer_ref, key_ref)
    cutoff = connector_time(now())
    if (
        grant is None
        or grant.revoked
        or not grant.valid_from <= cutoff < grant.expires_at
        or grant.producer_revision != config.producer_revision
        or any(fact.source not in grant.allowed_facts.get(fact.name, ()) for fact in facts)
    ):
        raise ValueError("observer preflight verifier is unavailable")
    context = ObserverDeploymentContext(
        target_ref=config.target_ref,
        discovery_digest=config.discovery_digest,
        observed_at=min(fact.observed_at for fact in facts),
        expires_at=min(min(fact.expires_at for fact in facts), grant.expires_at),
        private_cluster=True,
        facts=tuple(facts),
    )
    receipt = ObserverPreflightReceipt(
        issuer_ref=config.issuer_ref,
        key_ref=key_ref,
        producer_revision=config.producer_revision,
        context=context,
        issued_at=connector_time(now()),
        signature="0" * 128,
    )
    receipt = ObserverPreflightReceipt.model_validate(
        {**receipt.model_dump(), "signature": private.sign(receipt.signing_bytes()).hex()}
    )
    await verify_preflight(receipt, grants=grants, now=now(), clock=now)
    return receipt
