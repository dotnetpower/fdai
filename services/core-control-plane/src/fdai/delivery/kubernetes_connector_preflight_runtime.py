"""Deployment-owned verifier enrollment and bounded preflight runtime composition."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fdai_service_contracts.cluster_connector import ConnectorContract, Digest, connector_time
from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentContext,
    ObserverDeploymentProposal,
    ObserverPreflightReceipt,
    TargetRef,
)

from fdai.delivery.kubernetes_connector_preflight import (
    ObserverPreflightGrant,
    SignedObserverConstraints,
)
from fdai.delivery.kubernetes_connector_proposals import (
    ObserverConstraintReader,
    StateStoreObserverConstraints,
)
from fdai.delivery.kubernetes_connector_runtime import private_file
from fdai.shared.providers.state_store import StateStore

PREFLIGHT_GRANTS_ENV = "FDAI_OBSERVER_PREFLIGHT_GRANTS_PATH"


class ObserverReadPreflightConfig(ConnectorContract):
    """Private deployment binding; files contain references, never embedded credentials."""

    target_ref: TargetRef
    discovery_digest: Digest
    issuer_ref: TargetRef
    producer_revision: Digest
    api_origin: str
    namespace_uid: TargetRef
    api_ca_path: Path
    api_token_path: Path
    signing_key_path: Path
    grants_path: Path


class ObserverAdmissionPreflightConfig(ObserverReadPreflightConfig):
    """Deployment-preflight credential plus exact private draft inputs, never an observer grant."""

    installation_inputs_path: Path
    proposal_path: Path
    material_directory: Path


async def collect_read_preflight(
    path: Path, *, now: Callable[[], datetime]
) -> ObserverPreflightReceipt:
    """Perform only the exact reader's authorization probes and sign their observed fact."""
    return await _collect_preflight(path, now=now, admission=False)


async def collect_admission_preflight(
    path: Path, *, now: Callable[[], datetime]
) -> ObserverPreflightReceipt:
    """Inspect server admission using only dry-run creates; never install or grant approval."""
    return await _collect_preflight(path, now=now, admission=True)


async def _collect_preflight(
    path: Path, *, now: Callable[[], datetime], admission: bool
) -> ObserverPreflightReceipt:
    import hashlib

    from fdai.delivery.kubernetes_api_inventory import ServiceAccountTokenAuth
    from fdai.delivery.kubernetes_connector_preflight import verify_preflight
    from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight

    content = await asyncio.to_thread(private_file, path)
    config = (
        ObserverAdmissionPreflightConfig if admission else ObserverReadPreflightConfig
    ).model_validate(json.loads(content, object_pairs_hook=_unique))
    private = load_pem_private_key(
        await asyncio.to_thread(private_file, config.signing_key_path), password=None
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
        or "kubernetes_api"
        not in grant.allowed_facts.get("admission" if admission else "kubernetes_read", ())
    ):
        raise ValueError("observer preflight verifier is unavailable")
    tls = ssl.create_default_context(cafile=str(config.api_ca_path))
    probe = KubernetesObserverReadPreflight(
        origin=config.api_origin,
        target_ref=config.target_ref,
        namespace_uid=config.namespace_uid,
        auth=ServiceAccountTokenAuth(config.api_token_path),
        tls=tls,
        now=now,
    )
    if isinstance(config, ObserverAdmissionPreflightConfig):
        from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput

        inputs = ObserverInstallationInput.model_validate(
            json.loads(
                await asyncio.to_thread(private_file, config.installation_inputs_path),
                object_pairs_hook=_unique,
            )
        )
        proposal = ObserverDeploymentProposal.model_validate(
            json.loads(
                await asyncio.to_thread(private_file, config.proposal_path),
                object_pairs_hook=_unique,
            )
        )
        fact = await probe.collect_installation(
            inputs, proposal, material_directory=config.material_directory
        )
    else:
        fact = await probe.collect()
    context = ObserverDeploymentContext(
        target_ref=config.target_ref,
        discovery_digest=config.discovery_digest,
        observed_at=fact.observed_at,
        expires_at=min(fact.expires_at, grant.expires_at),
        private_cluster=True,
        facts=(fact,),
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


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("observer preflight configuration contains duplicate fields")
        values[key] = value
    return values


class FileObserverPreflightGrants:
    """Reload only private, bounded server configuration; receipts cannot enroll verifiers."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def read(
        self, target_ref: str, issuer_ref: str, key_ref: str
    ) -> ObserverPreflightGrant | None:
        entries = await asyncio.to_thread(self._entries)
        return next(
            (
                entry
                for entry in entries
                if (entry.target_ref, entry.issuer_ref, entry.key_ref)
                == (target_ref, issuer_ref, key_ref)
            ),
            None,
        )

    def _entries(self) -> tuple[ObserverPreflightGrant, ...]:
        values = json.loads(private_file(self._path), object_pairs_hook=_unique)
        if not isinstance(values, list) or not 1 <= len(values) <= 128:
            raise ValueError("observer verifier configuration requires 1 to 128 grants")
        entries = tuple(ObserverPreflightGrant.model_validate(value) for value in values)
        identities = [(entry.target_ref, entry.issuer_ref, entry.key_ref) for entry in entries]
        if len(set(identities)) != len(identities):
            raise ValueError("observer verifier configuration contains duplicate grants")
        return entries


def build_observer_constraints(
    store: StateStore, *, now: Callable[[], datetime]
) -> ObserverConstraintReader:
    path = os.environ.get(PREFLIGHT_GRANTS_ENV, "")
    if not path:
        return StateStoreObserverConstraints(store)
    return SignedObserverConstraints(store, grants=FileObserverPreflightGrants(Path(path)), now=now)


async def retain_preflight_file(
    path: Path, *, store: StateStore, now: Callable[[], datetime]
) -> bool:
    grant_path = os.environ.get(PREFLIGHT_GRANTS_ENV, "")
    if not grant_path:
        raise ValueError("observer preflight verifier configuration is required")
    content = await asyncio.to_thread(private_file, path)
    receipt = ObserverPreflightReceipt.model_validate(
        json.loads(content, object_pairs_hook=_unique)
    )
    source = SignedObserverConstraints(
        store, grants=FileObserverPreflightGrants(Path(grant_path)), now=now
    )
    async with asyncio.timeout(10):
        return await source.retain(receipt)
