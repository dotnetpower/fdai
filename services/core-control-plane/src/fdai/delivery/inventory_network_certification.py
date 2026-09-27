"""Run and independently verify one isolated Azure inventory network campaign."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import urlparse

import httpx
from psycopg.conninfo import conninfo_to_dict

from fdai.delivery.inventory_change_acceleration import (
    load_resource_type_registry,
    workload_identity,
)
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.inventory_sync_cli_support import build_sources, resolve_resource_types
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStore,
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.semantic_refresh_certification import certify_semantic_graph_refresh
from fdai.shared.providers.inventory import InventoryBatch
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySnapshotStore,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_FAULT_ARG_ENDPOINT = "https://arg-primary-unavailable.invalid"
_STORAGE_AUDIENCE = "https://storage.azure.com/.default"
_SOURCE_REVISION = "FDAI_NETWORK_CERT_SOURCE_REVISION"
_REQUEST_ID = "FDAI_NETWORK_CERT_REQUEST_ID"
_RECEIPT_URL = "FDAI_NETWORK_CERT_RECEIPT_URL"
_DIGEST_PREFIX = "sha256:"
_ALLOWED_PRIMARY_FAILURES = frozenset(
    {
        InventoryFailureCode.DNS_FAILED,
        InventoryFailureCode.NETWORK_BLOCKED,
        InventoryFailureCode.SOURCE_UNAVAILABLE,
    }
)


@dataclass(frozen=True, slots=True)
class InventoryNetworkStage:
    """Sanitized result of one ordered inventory stage."""

    source: str
    generation_digest: str
    failures: tuple[InventoryAttemptFailure, ...]
    active_during_failure_digest: str | None


@dataclass(frozen=True, slots=True)
class InventoryNetworkCampaignObservation:
    """Verified inputs reduced into a content-free campaign receipt."""

    source_revision: str
    request_id: str
    recorded_at: datetime
    binding_digest: str
    token_digest: str
    management_dns_digest: str
    management_tls_digest: str
    postgres_dns_digest: str
    postgres_tls_digest: str
    blob_dns_digest: str
    blob_tls_digest: str
    baseline: InventoryNetworkStage
    fallback: InventoryNetworkStage
    recovery: InventoryNetworkStage
    semantic_refresh: Mapping[str, object]


class _FailureObservingStore(InventorySnapshotStore):
    """Observe the active pointer after a failed source without changing store semantics."""

    def __init__(self, store: PostgresInventorySnapshotStore) -> None:
        self._store = store
        self.active_during_failure: str | None = None

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        return await self._store.begin(manifest)

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        await self._store.stage(attempt_id, batch)

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        await self._store.promote(attempt_id, manifest)

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        await self._store.fail(attempt_id, failure)
        self.active_during_failure = await self._store.active_snapshot_id()


def reduce_inventory_network_campaign(
    observation: InventoryNetworkCampaignObservation,
) -> dict[str, object]:
    """Return one no-authority receipt only when every campaign invariant holds."""

    if (
        observation.baseline.source != "arg"
        or observation.baseline.failures
        or observation.fallback.source != "arm"
        or len(observation.fallback.failures) != 1
        or observation.fallback.failures[0].code not in _ALLOWED_PRIMARY_FAILURES
        or observation.fallback.active_during_failure_digest
        != observation.baseline.generation_digest
        or observation.recovery.source != "arg"
        or observation.recovery.failures
        or not _valid_semantic_refresh(observation.semantic_refresh)
        or len(
            {
                observation.baseline.generation_digest,
                observation.fallback.generation_digest,
                observation.recovery.generation_digest,
            }
        )
        != 3
    ):
        raise ValueError("inventory network campaign did not prove fallback and recovery")
    axes = (
        ("workload_token", observation.token_digest),
        ("dns", observation.management_dns_digest),
        ("tcp_tls", observation.management_tls_digest),
        ("bounded_arg_query", observation.baseline.generation_digest),
        (
            "private_projection_write",
            _canonical_digest(
                {
                    "postgres_dns": observation.postgres_dns_digest,
                    "postgres_tls": observation.postgres_tls_digest,
                    "generation": observation.baseline.generation_digest,
                }
            ),
        ),
        (
            "primary_unavailable_fallback",
            _canonical_digest(
                {
                    "failure": observation.fallback.failures[0].code.value,
                    "retained": observation.fallback.active_during_failure_digest,
                    "fallback_generation": observation.fallback.generation_digest,
                }
            ),
        ),
        (
            "higher_priority_recovery",
            _canonical_digest(
                {
                    "binding": observation.binding_digest,
                    "generation": observation.recovery.generation_digest,
                }
            ),
        ),
        (
            "private_receipt_path",
            _canonical_digest(
                {
                    "blob_dns": observation.blob_dns_digest,
                    "blob_tls": observation.blob_tls_digest,
                }
            ),
        ),
    )
    body: dict[str, object] = {
        "schema_version": "fdai.inventory-network-certification.v1",
        "source_revision": observation.source_revision,
        "request_id": observation.request_id,
        "recorded_at": observation.recorded_at.astimezone(UTC).isoformat(),
        "binding_digest": observation.binding_digest,
        "axes": [
            {"name": name, "status": "passed", "evidence_digest": digest} for name, digest in axes
        ],
        "source_sequence": ["arg", "arm", "arg"],
        "semantic_refresh": dict(observation.semantic_refresh),
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return {**body, "digest": _canonical_digest(body)}


async def run_inventory_network_campaign(
    environment: Mapping[str, str],
    *,
    identity: WorkloadIdentity | None = None,
) -> dict[str, object]:
    """Run the exact bounded campaign and retain its receipt through private Blob."""

    source_revision = _source_revision(environment)
    request_id = _request_id(environment)
    receipt_url = _receipt_url(environment)
    receipt_private_ip = _receipt_private_ip(environment)
    config = InventoryJobConfig.from_env(environment)
    if (
        config.source_order != ("arg", "arm")
        or config.resource_types != ("resource-group",)
        or config.arg_endpoint not in (None, config.management_endpoint)
    ):
        raise ValueError("network certification requires bounded arg,arm resource-group scope")
    async with httpx.AsyncClient(follow_redirects=False) as client:
        active_identity = identity or workload_identity(http_client=client)
        management_token = await active_identity.get_token(config.management_audience)
        if (
            management_token.audience != config.management_audience
            or management_token.expires_at <= datetime.now(UTC)
        ):
            raise RuntimeError("workload token is invalid or expired")
        management_host = _https_host(config.management_endpoint)
        management_dns, management_tls = await _network_probe(management_host, 443)
        postgres_host = _postgres_host(config.dsn)
        postgres_dns, postgres_tls = await _network_probe(postgres_host, 5432)
        if not _all_private(postgres_dns):
            raise RuntimeError("inventory projection database did not resolve privately")
        receipt_host = _https_host(receipt_url)
        blob_dns, blob_tls = await _network_probe(
            receipt_host,
            443,
            connect_address=receipt_private_ip,
        )
        if not _all_private(blob_dns):
            raise RuntimeError("inventory receipt storage did not resolve privately")

        store = PostgresInventorySnapshotStore(
            config=PostgresInventorySnapshotStoreConfig(
                dsn=config.dsn,
                freshness_budget_seconds=config.freshness_budget_seconds,
            )
        )
        baseline = await _run_stage(config, store=store, identity=active_identity, client=client)
        fault = replace(config, arg_endpoint=_FAULT_ARG_ENDPOINT)
        fallback = await _run_stage(fault, store=store, identity=active_identity, client=client)
        recovery = await _run_stage(config, store=store, identity=active_identity, client=client)
        binding_digest = _binding_digest(config, environment)
        semantic_refresh = await certify_semantic_graph_refresh(
            dsn=config.dsn,
            scope_ref=config.scopes[0],
            source_revision=source_revision,
            request_id=request_id,
            provider_evidence_digest=baseline.generation_digest,
        )
        observation = InventoryNetworkCampaignObservation(
            source_revision=source_revision,
            request_id=request_id,
            recorded_at=datetime.now(UTC),
            binding_digest=binding_digest,
            token_digest=_canonical_digest(
                {
                    "audience": management_token.audience,
                    "identity": _identity_digest(environment),
                }
            ),
            management_dns_digest=_address_digest(management_dns),
            management_tls_digest=management_tls,
            postgres_dns_digest=_address_digest(postgres_dns),
            postgres_tls_digest=postgres_tls,
            blob_dns_digest=_address_digest(blob_dns),
            blob_tls_digest=blob_tls,
            baseline=baseline,
            fallback=fallback,
            recovery=recovery,
            semantic_refresh=semantic_refresh,
        )
        receipt = reduce_inventory_network_campaign(observation)
        encoded = _canonical_json(receipt) + b"\n"
        storage_token = await active_identity.get_token(_STORAGE_AUDIENCE)
        await _write_blob(
            receipt_url,
            encoded,
            token=storage_token.token,
            private_ip=receipt_private_ip,
        )
        observed = await _read_blob(
            receipt_url,
            token=storage_token.token,
            private_ip=receipt_private_ip,
        )
        if observed != encoded:
            raise RuntimeError("private inventory receipt readback did not match")
        return receipt


async def verify_inventory_network_campaign(
    environment: Mapping[str, str],
    *,
    identity: WorkloadIdentity | None = None,
) -> dict[str, object]:
    """Independently read and validate one private campaign receipt."""

    source_revision = _source_revision(environment)
    request_id = _request_id(environment)
    receipt_url = _receipt_url(environment)
    receipt_private_ip = _receipt_private_ip(environment)
    receipt_host = _https_host(receipt_url)
    addresses, tls_digest = await _network_probe(
        receipt_host,
        443,
        connect_address=receipt_private_ip,
    )
    if not _all_private(addresses):
        raise RuntimeError("inventory receipt verifier did not use a private address")
    async with httpx.AsyncClient(follow_redirects=False) as client:
        active_identity = identity or workload_identity(http_client=client)
        token = await active_identity.get_token(_STORAGE_AUDIENCE)
        encoded = await _read_blob(
            receipt_url,
            token=token.token,
            private_ip=receipt_private_ip,
        )
    try:
        receipt = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ValueError("inventory network receipt is not valid JSON") from exc
    if not isinstance(receipt, dict):
        raise ValueError("inventory network receipt MUST be an object")
    supplied_digest = receipt.pop("digest", None)
    axes = receipt.get("axes")
    if (
        supplied_digest != _canonical_digest(receipt)
        or receipt.get("schema_version") != "fdai.inventory-network-certification.v1"
        or receipt.get("source_revision") != source_revision
        or receipt.get("request_id") != request_id
        or receipt.get("source_sequence") != ["arg", "arm", "arg"]
        or not _valid_semantic_refresh(receipt.get("semantic_refresh"))
        or not isinstance(axes, list)
        or {item.get("name") for item in axes if isinstance(item, dict)}
        != {
            "workload_token",
            "dns",
            "tcp_tls",
            "bounded_arg_query",
            "private_projection_write",
            "primary_unavailable_fallback",
            "higher_priority_recovery",
            "private_receipt_path",
        }
        or any(
            not isinstance(item, dict)
            or item.get("status") != "passed"
            or not _is_digest(item.get("evidence_digest"))
            for item in axes
        )
        or receipt.get("observation_authority") is not False
        or receipt.get("mutation_authority") is not False
        or receipt.get("execution_authority") is not False
    ):
        raise ValueError("inventory network receipt failed independent verification")
    return {
        "schema_version": "fdai.inventory-network-certification-verification.v1",
        "source_revision": source_revision,
        "request_id": request_id,
        "receipt_digest": supplied_digest,
        "private_dns_digest": _address_digest(addresses),
        "tls_digest": tls_digest,
        "verified": True,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


async def _run_stage(
    config: InventoryJobConfig,
    *,
    store: PostgresInventorySnapshotStore,
    identity: WorkloadIdentity,
    client: httpx.AsyncClient,
) -> InventoryNetworkStage:
    vocabulary = load_resource_type_registry()
    resource_types = resolve_resource_types(config, vocabulary)
    observing = _FailureObservingStore(store)
    result = await InventorySyncCoordinator(store=observing).run(
        build_sources(
            config=config,
            vocabulary=vocabulary,
            resource_types=resource_types,
            identity=identity,
            http_client=client,
            started_at=datetime.now(UTC),
        )
    )
    active = await store.active_snapshot_id()
    if active != result.attempt_id:
        raise RuntimeError("inventory network stage active generation readback failed")
    return InventoryNetworkStage(
        source=result.source,
        generation_digest=_opaque_digest(result.attempt_id),
        failures=result.failures,
        active_during_failure_digest=(
            _opaque_digest(observing.active_during_failure)
            if observing.active_during_failure is not None
            else None
        ),
    )


async def _network_probe(
    host: str,
    port: int,
    *,
    connect_address: str | None = None,
) -> tuple[tuple[str, ...], str]:
    if connect_address is None:
        loop = asyncio.get_running_loop()
        try:
            values = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=10,
            )
        except (OSError, TimeoutError) as exc:
            raise RuntimeError("network certification DNS probe failed") from exc
        addresses = tuple(sorted({str(item[4][0]) for item in values}))
    else:
        addresses = (connect_address,)
    if not addresses or len(addresses) > 16:
        raise RuntimeError("network certification DNS result is outside the reviewed bound")
    context = ssl.create_default_context()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                connect_address or host,
                port,
                ssl=context,
                server_hostname=host,
            ),
            timeout=15,
        )
    except (OSError, TimeoutError, ssl.SSLError) as exc:
        raise RuntimeError("network certification TCP/TLS probe failed") from exc
    ssl_object = writer.get_extra_info("ssl_object")
    cipher = ssl_object.cipher() if ssl_object is not None else None
    await _close_tls_writer(writer)
    if not cipher:
        raise RuntimeError("network certification TLS negotiation is unavailable")
    return addresses, _canonical_digest({"host": _opaque_digest(host), "cipher": cipher[0]})


async def _close_tls_writer(writer: asyncio.StreamWriter) -> None:
    """Close a proven TLS stream without converting shutdown latency into probe failure."""

    writer.close()
    with suppress(TimeoutError, ConnectionError, ssl.SSLError):
        await writer.wait_closed()


async def _write_blob(
    url: str,
    content: bytes,
    *,
    token: str,
    private_ip: str,
) -> None:
    status, _ = await asyncio.to_thread(
        _storage_request,
        "PUT",
        url,
        token=token,
        private_ip=private_ip,
        content=content,
    )
    if status != 201:
        raise RuntimeError(f"private receipt write failed with HTTP {status}")


async def _read_blob(url: str, *, token: str, private_ip: str) -> bytes:
    status, body = await asyncio.to_thread(
        _storage_request,
        "GET",
        url,
        token=token,
        private_ip=private_ip,
        content=b"",
    )
    if status != 200 or len(body) > 256 * 1024:
        raise RuntimeError(f"private receipt read failed with HTTP {status}")
    return body


def _storage_request(
    method: str,
    url: str,
    *,
    token: str,
    private_ip: str,
    content: bytes,
) -> tuple[int, bytes]:
    parsed = urlparse(url)
    host = parsed.hostname
    if (
        host is None
        or parsed.scheme != "https"
        or method not in {"GET", "PUT"}
        or not ipaddress.ip_address(private_ip).is_private
    ):
        raise ValueError("private storage request binding is invalid")
    path = parsed.path or "/"
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(host, timeout=30, context=context)
    stream = socket.create_connection((private_ip, 443), timeout=15)
    connection.sock = context.wrap_socket(stream, server_hostname=host)
    headers = _storage_headers(token)
    headers["Host"] = host
    if method == "PUT":
        headers.update(
            {
                "Content-Length": str(len(content)),
                "Content-Type": "application/json",
                "x-ms-blob-type": "BlockBlob",
            }
        )
    try:
        connection.request(method, path, body=content if method == "PUT" else None, headers=headers)
        response = connection.getresponse()
        body = response.read(256 * 1024 + 1)
        return response.status, body
    finally:
        connection.close()


def _storage_headers(token: str) -> dict[str, str]:
    if not token:
        raise ValueError("storage token MUST NOT be empty")
    return {
        "Authorization": f"Bearer {token}",
        "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
        "x-ms-version": "2023-11-03",
    }


def _binding_digest(config: InventoryJobConfig, environment: Mapping[str, str]) -> str:
    return _canonical_digest(
        {
            "identity": _identity_digest(environment),
            "scope": _canonical_digest({"scopes": sorted(config.scopes)}),
            "resource_types": config.resource_types,
            "source_order": config.source_order,
            "management_origin": config.management_endpoint,
            "management_audience": config.management_audience,
            "arg_requests_per_second": config.arg_requests_per_second,
            "collection_policy": (
                asdict(config.collection_policy) if config.collection_policy is not None else None
            ),
        }
    )


def _identity_digest(environment: Mapping[str, str]) -> str:
    client_id = environment.get("FDAI_MI_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("FDAI_MI_CLIENT_ID is required")
    return _opaque_digest(client_id.casefold())


def _source_revision(environment: Mapping[str, str]) -> str:
    value = environment.get(_SOURCE_REVISION, "").strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{_SOURCE_REVISION} MUST be a full lowercase commit SHA")
    return value


def _request_id(environment: Mapping[str, str]) -> str:
    value = environment.get(_REQUEST_ID, "").strip()
    if (
        not value.startswith("inventory-network-")
        or len(value) != 66
        or any(character not in "0123456789abcdef" for character in value[18:])
    ):
        raise ValueError(f"{_REQUEST_ID} MUST be inventory-network- plus 48 hex characters")
    return value


def _receipt_url(environment: Mapping[str, str]) -> str:
    value = environment.get(_RECEIPT_URL, "").strip()
    parsed = urlparse(value)
    segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not parsed.hostname.endswith(".blob.core.windows.net")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(segments) != 2
        or segments[1] != f"{_request_id(environment)}.json"
    ):
        raise ValueError(f"{_RECEIPT_URL} MUST be one credential-free Azure Blob URL")
    return value


def _receipt_private_ip(environment: Mapping[str, str]) -> str:
    value = environment.get("FDAI_NETWORK_CERT_RECEIPT_PRIVATE_IP", "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("FDAI_NETWORK_CERT_RECEIPT_PRIVATE_IP MUST be one IP address") from exc
    if not address.is_private:
        raise ValueError("FDAI_NETWORK_CERT_RECEIPT_PRIVATE_IP MUST be private")
    return value


def _postgres_host(dsn: str) -> str:
    try:
        host = str(conninfo_to_dict(dsn).get("host") or "").strip()
    except Exception as exc:
        raise ValueError("inventory certification DSN is invalid") from exc
    if not host or "/" in host:
        raise ValueError("inventory certification DSN requires one TCP hostname")
    return host


def _https_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname is None:
        raise ValueError("network certification endpoint MUST be HTTPS")
    return parsed.hostname


def _all_private(addresses: Sequence[str]) -> bool:
    return bool(addresses) and all(ipaddress.ip_address(value).is_private for value in addresses)


def _address_digest(addresses: Sequence[str]) -> str:
    return _canonical_digest(
        {"address_digests": sorted(_opaque_digest(value) for value in addresses)}
    )


def _opaque_digest(value: str) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith(_DIGEST_PREFIX)
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _valid_semantic_refresh(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    statuses = value.get("evidence_statuses")
    return (
        value.get("schema_version") == "fdai.semantic-graph-refresh-certification.v1"
        and statuses == ["complete", "conflicting", "incomplete", "stale", "unavailable"]
        and value.get("provider_read_count") == 1
        and value.get("gateway_requery_count") == 1
        and value.get("audit_chain_verified") is True
        and value.get("observation_authority") is False
        and value.get("mutation_authority") is False
        and value.get("execution_authority") is False
        and _is_digest(value.get("digest"))
        and _is_digest(value.get("write_through_digest"))
    )


__all__ = [
    "InventoryNetworkCampaignObservation",
    "InventoryNetworkStage",
    "reduce_inventory_network_campaign",
    "run_inventory_network_campaign",
    "verify_inventory_network_campaign",
]
