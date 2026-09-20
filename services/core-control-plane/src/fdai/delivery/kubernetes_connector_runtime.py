"""Explicit composition for certificate-authenticated observer and gateway workloads."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import ssl
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

import httpx
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from fdai_service_contracts.cluster_connector import ConnectorRegistration, Digest, OpaqueRef
from fdai_service_contracts.venue import ExecutionVenue, resolve_execution_venue
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventoryConfig,
    KubernetesApiInventorySource,
    ServiceAccountTokenAuth,
)
from fdai.delivery.kubernetes_connector_gateway import create_connector_gateway
from fdai.delivery.kubernetes_connector_snapshot import (
    ConnectorInventorySource,
    ConnectorSnapshotInbox,
)
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.kubernetes_connector_transport import (
    ConnectorEvidenceTransport,
    ConnectorTransportConfig,
)
from fdai.delivery.kubernetes_connector_worker import ConnectorObserverWorker
from fdai.shared.providers.state_store import StateStore


class ConnectorRuntimeConfig(BaseModel):
    """Reference deployment-owned files; no bearer token, password, or DSN value belongs here."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["observer", "gateway"]
    registration_path: Path
    tls_ca_path: Path
    tls_certificate_path: Path
    tls_key_path: Path
    allow_cluster_resources: Annotated[bool, Field(strict=True)] = False
    max_age_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 300
    gateway_origin: str | None = None
    observer_principal_ref: Digest | None = None
    stream_id: OpaqueRef | None = None
    producer_revision: Digest | None = None
    spool_directory: Path | None = None
    api_server: str | None = None
    api_ca_path: Path | None = None
    api_token_path: Path | None = None
    listen_host: str = "127.0.0.1"
    listen_port: Annotated[int, Field(strict=True, ge=1024, le=65535)] = 8443

    @field_validator("listen_host")
    @classmethod
    def _listen_address(cls, value: str) -> str:
        return str(ipaddress.ip_address(value))

    @model_validator(mode="after")
    def _validate_role(self) -> Self:
        observer = (
            self.gateway_origin,
            self.observer_principal_ref,
            self.stream_id,
            self.producer_revision,
            self.spool_directory,
            self.api_server,
            self.api_ca_path,
            self.api_token_path,
        )
        if self.role == "observer" and any(value is None for value in observer):
            raise ValueError("connector observer configuration is incomplete")
        if self.role == "gateway" and any(value is not None for value in observer):
            raise ValueError("connector gateway must not receive observer credentials")
        if self.role == "observer":
            ConnectorTransportConfig(self.gateway_origin or "", "mtls")
            KubernetesApiInventoryConfig(self.api_server or "", "configuration-validation")
        return self


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("connector configuration has duplicate fields")
        result[key] = value
    return result


def private_file(path: Path, *, maximum: int = 131_072) -> bytes:
    """Read bounded owner-only deployment material without following the final symlink."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > maximum
        ):
            raise ValueError("connector file must be bounded and owner-only")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError("connector file exceeds the configured limit")
        return content
    finally:
        os.close(descriptor)


def load_connector_config(path: Path) -> ConnectorRuntimeConfig:
    return ConnectorRuntimeConfig.model_validate(
        json.loads(private_file(path), object_pairs_hook=_unique_fields)
    )


class FileConnectorRegistrations:
    """Reload a protected deployment-owned enrollment file on every admission check."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def read(self, principal_ref: str) -> ConnectorRegistration | None:
        return await asyncio.to_thread(self._read, principal_ref)

    def _read(self, principal_ref: str) -> ConnectorRegistration | None:
        return next(
            (entry for entry in self._entries() if entry.principal_ref == principal_ref), None
        )

    async def for_target(self, target_ref: str) -> ConnectorRegistration | None:
        entries = await asyncio.to_thread(self._entries)
        matches = [entry for entry in entries if entry.scope.cluster_ref == target_ref]
        if len(matches) > 1:
            raise ValueError("connector target has ambiguous observer enrollments")
        return matches[0] if matches else None

    def _entries(self) -> tuple[ConnectorRegistration, ...]:
        value = json.loads(private_file(self._path), object_pairs_hook=_unique_fields)
        if not isinstance(value, list) or not 1 <= len(value) <= 32:
            raise ValueError("connector registrations must contain 1 to 32 entries")
        entries = [ConnectorRegistration.model_validate(item) for item in value]
        principals = [entry.principal_ref for entry in entries]
        scopes = [(entry.scope.deployment_ref, entry.scope.cluster_ref) for entry in entries]
        if len(set(principals)) != len(principals) or len(set(scopes)) != len(scopes):
            raise ValueError(
                "connector registrations must have unique principals and cluster bindings"
            )
        if any(entry.role != "observer" for entry in entries):
            raise ValueError("snapshot gateway admits only observer enrollments")
        return tuple(entries)


def connector_tls(config: ConnectorRuntimeConfig) -> ssl.SSLContext:
    """Load an explicit trust root and certificate while requiring peer verification."""
    private_file(config.tls_key_path)
    purpose = ssl.Purpose.SERVER_AUTH if config.role == "observer" else ssl.Purpose.CLIENT_AUTH
    context = ssl.create_default_context(purpose, cafile=str(config.tls_ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(str(config.tls_certificate_path), str(config.tls_key_path))
    if config.role == "observer":
        certificate = x509.load_pem_x509_certificate(config.tls_certificate_path.read_bytes())
        fingerprint = "sha256:" + hashlib.sha256(certificate.public_bytes(Encoding.DER)).hexdigest()
        if fingerprint != config.observer_principal_ref:
            raise ValueError("connector certificate does not match its registered principal")
    return context


async def observe_once(config: ConnectorRuntimeConfig) -> dict[str, object]:
    """Run one real ServiceAccount collection and mTLS transfer with no central DB access."""
    if config.role != "observer":
        raise ValueError("connector observer role required")
    registrations = FileConnectorRegistrations(config.registration_path)
    principal = config.observer_principal_ref or ""
    registration = await registrations.read(principal)
    if registration is None:
        raise ValueError("connector observer enrollment is unavailable")
    if (
        config.api_ca_path is None
        or config.api_token_path is None
        or config.spool_directory is None
    ):
        raise ValueError("connector observer file references are incomplete")
    tls = connector_tls(config)
    async with httpx.AsyncClient(
        verify=str(config.api_ca_path), trust_env=False, follow_redirects=False
    ) as client:
        source = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                config.api_server or "", registration.scope.cluster_ref
            ),
            auth=ServiceAccountTokenAuth(config.api_token_path),
            http_client=client,
        )
        spool = ConnectorSnapshotSpool(
            config.spool_directory,
            registration=registration,
            stream_id=config.stream_id or "",
            allow_cluster_resources=config.allow_cluster_resources,
        )
        sender = ConnectorEvidenceTransport(
            ConnectorTransportConfig(config.gateway_origin or "", "mtls"), tls_context=tls
        )
        try:
            worker = ConnectorObserverWorker(
                source=source,
                spool=spool,
                sender=sender,
                registrations=registrations,
                principal_ref=principal,
                producer_revision=config.producer_revision or "",
                allow_cluster_resources=config.allow_cluster_resources,
                now=lambda: datetime.now(UTC),
                max_age_seconds=config.max_age_seconds,
            )
            receipt = await worker.run_once()
            return {
                "status": receipt.status.value,
                "evidence_digest": receipt.evidence_digest,
                "sequence": receipt.sequence,
                "inventory_promotion": False,
            }
        finally:
            await sender.aclose()


def build_snapshot_inbox(
    config: ConnectorRuntimeConfig, store: StateStore
) -> ConnectorSnapshotInbox:
    """Compose the same server-owned registry for HTTP admission and inventory reads."""
    return ConnectorSnapshotInbox(
        store,
        registrations=FileConnectorRegistrations(config.registration_path),
        allow_cluster_resources=config.allow_cluster_resources,
        now=lambda: datetime.now(UTC),
        max_age_seconds=config.max_age_seconds,
    )


def connector_inventory_source(
    config: ConnectorRuntimeConfig, *, store: StateStore, principal_ref: str
) -> ConnectorInventorySource:
    return ConnectorInventorySource(
        build_snapshot_inbox(config, store), principal_ref=principal_ref
    )


def run_gateway(config: ConnectorRuntimeConfig) -> None:
    """Run the dedicated Core-owned mTLS ingress against its service-owned state store."""
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

    if config.role != "gateway":
        raise ValueError("connector gateway role required")
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    if not dsn:
        raise ValueError("connector gateway requires the service-owned state store")
    validate_connector_database_venue(dsn)
    store = PostgresStateStore(
        config=PostgresStateStoreConfig(dsn=dsn, connect_timeout_s=3, statement_timeout_ms=5000)
    )
    registrations = FileConnectorRegistrations(config.registration_path)
    app = create_connector_gateway(
        inbox=build_snapshot_inbox(config, store),
        registrations=registrations,
        now=lambda: datetime.now(UTC),
    )
    web.run_app(
        app,
        host=config.listen_host,
        port=config.listen_port,
        ssl_context=connector_tls(config),
        access_log=None,
        print=None,
    )


def validate_connector_database_venue(dsn: str) -> None:
    """Prevent a local connector gateway from accessing a remote runtime database."""
    parameters = conninfo_to_dict(dsn)
    if resolve_execution_venue(os.environ) is ExecutionVenue.LOCAL and (
        parameters.get("host") not in {"localhost", "127.0.0.1", "::1"}
        or parameters.get("hostaddr") not in {None, "127.0.0.1", "::1"}
        or parameters.get("service") is not None
    ):
        raise ValueError("local connector gateway requires a loopback database")
