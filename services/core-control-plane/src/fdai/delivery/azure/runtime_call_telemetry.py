"""Read exact runtime-call identities from Azure Monitor without granting authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx

from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
)
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.runtime_call_inventory import (
    RuntimeCallTelemetryBatch,
    RuntimeCallTelemetryRecord,
)
from fdai.shared.providers.observation import LogQueryProvider
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_ROWS = 2_000
_MAX_ENDPOINT_REPLICAS = 32
_MAX_ENDPOINT_VERIFICATION_CONCURRENCY = 4
_DEFAULT_PENDING_GRACE_SECONDS = 60
_SOURCE_IDENTITY = "azure-monitor.container-app-runtime-calls"
_SOURCE_REVISION = "2.1.0"
_SOURCE_CREDENTIAL_LINEAGE = "azure-monitor.container-app-console-ingestion"
_VERIFIER_IDENTITY = "inventory.runtime-call-authenticator"
_VERIFIER_CREDENTIAL_LINEAGE = "azure-resource-manager.query-managed-identity"
_ENDPOINT_LOG_SCHEMA = "fdai.runtime-call-endpoint-log@1.0.0"
_CONTAINER_APP_PROVIDER_TYPE = "microsoft.app/containerapps"
_CONTAINER_APP_API_VERSION = "2025-01-01"
_REVISION_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,63}$")
_REPLICA_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,127}$")

RUNTIME_CALL_TELEMETRY_KQL = """
ContainerAppConsoleLogs_CL
| extend record = parse_json(Log_s)
| where tostring(record.message) == "runtime_call_endpoint_observed"
| project
    observed_at = TimeGenerated,
    schema_version = tostring(record.schema_version),
    observation_id = tostring(record.observation_id),
    caller_resource_id = tostring(record.caller_resource_id),
    target_resource_id = tostring(record.target_resource_id),
    endpoint_role = tostring(record.endpoint_role),
    platform_resource_id = tostring(_ResourceId),
    platform_name = tostring(ContainerAppName_s),
    platform_revision_name = tostring(RevisionName_s),
    platform_replica_name = tostring(ContainerGroupName_s),
    execution_authority = tobool(record.execution_authority),
    mutation_authority = tobool(record.mutation_authority),
    source_container_group_id = tostring(ContainerGroupId_g),
    source_container_id = tostring(ContainerId_g),
    source_platform_timestamp = tostring(_timestamp_d),
    table_name = "ContainerAppConsoleLogs_CL"
| order by observed_at asc, observation_id asc, source_container_id asc
""".strip()


class RuntimeCallTelemetryContextProvider(Protocol):
    """Supply independently authenticated context for one telemetry envelope."""

    async def context_for(
        self,
        envelope: RuntimeCallTelemetryEnvelope,
    ) -> AuthenticatedRuntimeCallContext: ...


class RuntimeCallEndpointIdentityVerifier(Protocol):
    """Verify one platform revision under an exact endpoint Resource ID."""

    async def verify(
        self,
        *,
        resource_id: str,
        revision_name: str,
        replica_name: str,
    ) -> bool: ...


class AzureContainerAppRevisionVerifier:
    """Verify a platform-stamped revision through its exact ARM parent."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        management_endpoint: str = "https://management.azure.com",
        management_audience: str = "https://management.azure.com/.default",
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urlparse(management_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("runtime call management endpoint MUST be an HTTPS origin")
        if not management_audience.strip() or timeout_seconds <= 0:
            raise ValueError("runtime call ARM verifier configuration is invalid")
        self._identity = identity
        self._http = http_client
        self._management_endpoint = management_endpoint.rstrip("/")
        self._management_audience = management_audience
        self._timeout_seconds = timeout_seconds

    async def verify(
        self,
        *,
        resource_id: str,
        revision_name: str,
        replica_name: str,
    ) -> bool:
        """Return whether the exact ARM app owns the platform replica."""

        _validate_container_app_resource_id(resource_id, field_name="resource_id")
        if _REVISION_NAME.fullmatch(revision_name) is None:
            raise ValueError("runtime call revision name is invalid")
        if _REPLICA_NAME.fullmatch(replica_name) is None:
            raise ValueError("runtime call replica name is invalid")
        token = await self._identity.get_token(self._management_audience)
        expected_id = f"{resource_id}/revisions/{revision_name}/replicas/{replica_name}"
        response = await self._http.get(
            (
                f"{self._management_endpoint}{resource_id}/revisions/"
                f"{quote(revision_name, safe='')}/replicas/{quote(replica_name, safe='')}"
            ),
            params={"api-version": _CONTAINER_APP_API_VERSION},
            headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
            timeout=self._timeout_seconds,
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("runtime call ARM revision response MUST be an object")
        returned_id = payload.get("id")
        returned_name = payload.get("name")
        return (
            isinstance(returned_id, str)
            and returned_id.casefold() == expected_id.casefold()
            and isinstance(returned_name, str)
            and returned_name.casefold() == replica_name.casefold()
        )


class AzureMonitorRuntimeCallContextProvider:
    """Authenticate paired platform and ARM-verified endpoint witnesses."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    async def context_for(
        self,
        envelope: RuntimeCallTelemetryEnvelope,
    ) -> AuthenticatedRuntimeCallContext:
        """Bind the authenticated query result to the exact telemetry content."""

        if envelope.source_identity != _SOURCE_IDENTITY:
            raise ValueError("runtime call telemetry source identity is not trusted")
        if not _is_digest(envelope.evidence_ref):
            raise ValueError("runtime call telemetry evidence_ref MUST be canonical SHA-256")
        verified_at = self._clock()
        if verified_at.tzinfo is None:
            raise ValueError("runtime call telemetry verification clock MUST be timezone-aware")
        verified_at = max(verified_at.astimezone(UTC), envelope.recorded_at.astimezone(UTC))
        return AuthenticatedRuntimeCallContext(
            observation_id=envelope.observation_id,
            observation_digest=envelope.content_digest(),
            source_identity=envelope.source_identity,
            source_credential_lineage=_SOURCE_CREDENTIAL_LINEAGE,
            verifier_identity=_VERIFIER_IDENTITY,
            verifier_credential_lineage=_VERIFIER_CREDENTIAL_LINEAGE,
            authentication_ref=_digest(
                {
                    "evidence_ref": envelope.evidence_ref,
                    "observation_digest": envelope.content_digest(),
                    "source_credential_lineage": _SOURCE_CREDENTIAL_LINEAGE,
                    "verifier_credential_lineage": _VERIFIER_CREDENTIAL_LINEAGE,
                }
            ),
            verified_at=verified_at,
            signature_verified=True,
        )


class AzureMonitorRuntimeCallAuthenticator:
    """Revalidate the pinned Azure Monitor authentication lineages."""

    async def authenticate(
        self,
        *,
        envelope: RuntimeCallTelemetryEnvelope,
        claimed_context: AuthenticatedRuntimeCallContext,
    ) -> AuthenticatedRuntimeCallContext:
        """Return only a context issued for the reviewed Azure Monitor source."""

        if (
            envelope.source_identity != _SOURCE_IDENTITY
            or claimed_context.source_credential_lineage != _SOURCE_CREDENTIAL_LINEAGE
            or claimed_context.verifier_identity != _VERIFIER_IDENTITY
            or claimed_context.verifier_credential_lineage != _VERIFIER_CREDENTIAL_LINEAGE
        ):
            raise ValueError("runtime call telemetry authentication lineage is not trusted")
        return claimed_context


@dataclass(frozen=True, slots=True)
class _EndpointWitness:
    observation_id: str
    endpoint_role: str
    caller_arm_id: str
    target_arm_id: str
    platform_revision_name: str
    platform_replica_name: str
    observed_at: datetime
    evidence_ref: str

    @property
    def endpoint_arm_id(self) -> str:
        """Return the endpoint asserted by this witness role."""

        return self.caller_arm_id if self.endpoint_role == "caller" else self.target_arm_id


class AzureRuntimeCallTelemetrySource:
    """Collect bounded caller and target identities from a configured log provider."""

    def __init__(
        self,
        *,
        provider: LogQueryProvider,
        context_provider: RuntimeCallTelemetryContextProvider,
        endpoint_verifier: RuntimeCallEndpointIdentityVerifier,
        scope_ref: str,
        source_identity: str = _SOURCE_IDENTITY,
        source_revision: str = _SOURCE_REVISION,
        freshness_ceiling_seconds: int = 300,
        max_rows: int = _MAX_ROWS,
        clock: Callable[[], datetime] | None = None,
        endpoint_verification_deadline_seconds: float = 30.0,
        pending_grace_seconds: int = _DEFAULT_PENDING_GRACE_SECONDS,
    ) -> None:
        if not 1 <= max_rows <= _MAX_ROWS:
            raise ValueError(f"runtime call telemetry max_rows MUST be in [1, {_MAX_ROWS}]")
        if not scope_ref.strip() or not source_identity.strip() or not source_revision.strip():
            raise ValueError("runtime call telemetry source identity fields MUST be non-empty")
        if freshness_ceiling_seconds < 1:
            raise ValueError("runtime call telemetry freshness ceiling MUST be positive")
        if not 0 < endpoint_verification_deadline_seconds <= 120:
            raise ValueError("runtime call endpoint verification deadline MUST be in (0, 120]")
        if not 1 <= pending_grace_seconds <= 300:
            raise ValueError("runtime call pending grace MUST be in [1, 300]")
        self._provider = provider
        self._context_provider = context_provider
        self._endpoint_verifier = endpoint_verifier
        self._scope_ref = scope_ref
        self._source_identity = source_identity
        self._source_revision = source_revision
        self._freshness_ceiling_seconds = freshness_ceiling_seconds
        self._max_rows = max_rows
        self._clock = clock or (lambda: datetime.now(UTC))
        self._endpoint_verification_deadline_seconds = endpoint_verification_deadline_seconds
        self._pending_grace_seconds = pending_grace_seconds

    async def collect(self, _observation: object) -> RuntimeCallTelemetryBatch:
        """Return a complete typed batch or explicit incomplete evidence."""

        try:
            result = await self._provider.query_log(
                query=RUNTIME_CALL_TELEMETRY_KQL,
                window=(f"PT{self._freshness_ceiling_seconds + self._pending_grace_seconds}S"),
                max_rows=self._max_rows,
            )
        except Exception:  # noqa: BLE001 - source details never enter coverage metadata
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_source_unavailable",
                coverage={"unavailable_rows": 1},
            )
        if result.truncated:
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_rows_incomplete",
                coverage={"unavailable_rows": 1},
            )
        parsed_witnesses: list[_EndpointWitness] = []
        coverage = {
            "unavailable_rows": 0,
            "redacted_rows": 0,
            "malformed_rows": 0,
        }
        for row in result.rows:
            try:
                witness = self._witness(row)
            except KeyError:
                coverage["redacted_rows"] += 1
                continue
            except ValueError:
                coverage["malformed_rows"] += 1
                continue
            parsed_witnesses.append(witness)
        if not parsed_witnesses:
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason=(
                    "telemetry_rows_incomplete"
                    if any(coverage.values())
                    else "telemetry_source_unavailable"
                ),
                coverage=coverage if any(coverage.values()) else {"unavailable_rows": 1},
            )
        verification_started_at = self._clock()
        if verification_started_at.tzinfo is None:
            raise ValueError("runtime call telemetry clock MUST be timezone-aware")
        verification_started_at = verification_started_at.astimezone(UTC)
        witnesses_by_observation: dict[tuple[str, str, str], list[_EndpointWitness]] = {}
        for witness in parsed_witnesses:
            witnesses_by_observation.setdefault(
                (
                    witness.observation_id,
                    witness.caller_arm_id,
                    witness.target_arm_id,
                ),
                [],
            ).append(witness)
        stale_observations = {
            key
            for key, grouped_witnesses in witnesses_by_observation.items()
            if (
                verification_started_at - max(witness.observed_at for witness in grouped_witnesses)
            ).total_seconds()
            > self._freshness_ceiling_seconds
        }
        current_witnesses = [
            witness
            for key, grouped_witnesses in witnesses_by_observation.items()
            if key not in stale_observations
            for witness in grouped_witnesses
        ]
        replica_keys = {
            (
                witness.endpoint_arm_id,
                witness.platform_revision_name,
                witness.platform_replica_name,
            )
            for witness in current_witnesses
        }
        if len(replica_keys) > _MAX_ENDPOINT_REPLICAS:
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_rows_incomplete",
                coverage={"unavailable_rows": len(replica_keys)},
            )
        verification_semaphore = asyncio.Semaphore(_MAX_ENDPOINT_VERIFICATION_CONCURRENCY)

        async def verify_replica(
            key: tuple[str, str, str],
        ) -> tuple[tuple[str, str, str], bool]:
            resource_id, revision_name, replica_name = key
            async with verification_semaphore:
                try:
                    verified = await self._endpoint_verifier.verify(
                        resource_id=resource_id,
                        revision_name=revision_name,
                        replica_name=replica_name,
                    )
                except (httpx.HTTPError, ValueError):
                    verified = False
            return key, verified

        try:
            async with asyncio.timeout(self._endpoint_verification_deadline_seconds):
                verified_replicas = dict(
                    await asyncio.gather(*(verify_replica(key) for key in sorted(replica_keys)))
                )
        except TimeoutError:
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_deadline_exceeded",
                coverage={"unavailable_rows": len(replica_keys)},
            )
        recorded_at = self._clock()
        if recorded_at.tzinfo is None:
            raise ValueError("runtime call telemetry clock MUST be timezone-aware")
        recorded_at = recorded_at.astimezone(UTC)
        witnesses: dict[tuple[str, str, str], dict[str, _EndpointWitness]] = {}
        for witness in current_witnesses:
            if not verified_replicas[
                (
                    witness.endpoint_arm_id,
                    witness.platform_revision_name,
                    witness.platform_replica_name,
                )
            ]:
                coverage["unavailable_rows"] += 1
                continue
            if witness.observed_at > recorded_at:
                coverage["malformed_rows"] += 1
                continue
            witness_key = (
                witness.observation_id,
                witness.caller_arm_id,
                witness.target_arm_id,
            )
            by_role = witnesses.setdefault(witness_key, {})
            previous_witness = by_role.get(witness.endpoint_role)
            if previous_witness is None or _witness_order(witness) > _witness_order(
                previous_witness
            ):
                by_role[witness.endpoint_role] = witness
        endpoint_pairs_by_observation: dict[str, set[tuple[str, str]]] = {}
        for observation_id, caller_arm_id, target_arm_id in witnesses:
            endpoint_pairs_by_observation.setdefault(observation_id, set()).add(
                (caller_arm_id, target_arm_id)
            )
        ambiguous_observations = {
            observation_id
            for observation_id, endpoint_pairs in endpoint_pairs_by_observation.items()
            if len(endpoint_pairs) != 1
        }
        coverage["malformed_rows"] += len(ambiguous_observations)
        records_by_edge: dict[tuple[str, str], RuntimeCallTelemetryRecord] = {}
        for witness_key in sorted(witnesses):
            if witness_key[0] in ambiguous_observations:
                continue
            by_role = witnesses[witness_key]
            latest_observed_at = max(witness.observed_at for witness in by_role.values())
            age_seconds = (recorded_at - latest_observed_at).total_seconds()
            if age_seconds > self._freshness_ceiling_seconds:
                continue
            if set(by_role) != {"caller", "target"}:
                if age_seconds <= self._pending_grace_seconds:
                    continue
                coverage["unavailable_rows"] += 1
                continue
            envelope = self._envelope(
                caller=by_role["caller"],
                target=by_role["target"],
                recorded_at=recorded_at,
            )
            try:
                context = await self._context_provider.context_for(envelope)
            except Exception:  # noqa: BLE001 - authentication remains fail closed
                coverage["unavailable_rows"] += 1
                continue
            record = RuntimeCallTelemetryRecord(envelope, context)
            edge_key = (envelope.caller_resource_ids[0], envelope.target_resource_ids[0])
            previous = records_by_edge.get(edge_key)
            if previous is None or _record_order(record) > _record_order(previous):
                records_by_edge[edge_key] = record
        if any(coverage.values()):
            return RuntimeCallTelemetryBatch(
                records=(),
                observed_at=None,
                complete=False,
                reason="telemetry_rows_incomplete",
                coverage=coverage,
            )
        return RuntimeCallTelemetryBatch(
            records=tuple(records_by_edge[key] for key in sorted(records_by_edge)),
            observed_at=recorded_at,
            complete=True,
        )

    def _witness(
        self,
        row: Mapping[str, Any],
    ) -> _EndpointWitness:
        if _required_text(row, "table_name", classify_missing=True) != "ContainerAppConsoleLogs_CL":
            raise ValueError("runtime call telemetry table is not trusted")
        if _required_text(row, "schema_version", classify_missing=True) != _ENDPOINT_LOG_SCHEMA:
            raise ValueError("runtime call telemetry schema is not trusted")
        _required_false(row, "execution_authority")
        _required_false(row, "mutation_authority")
        observation_id = _required_digest(row, "observation_id")
        endpoint_role = _required_text(row, "endpoint_role", classify_missing=True)
        if endpoint_role not in {"caller", "target"}:
            raise ValueError("runtime call telemetry endpoint_role is not trusted")
        caller_arm_id = _required_text(row, "caller_resource_id", classify_missing=True)
        target_arm_id = _required_text(row, "target_resource_id", classify_missing=True)
        platform_name = _required_text(
            row,
            "platform_name",
            classify_missing=True,
        )
        platform_revision_name = _required_text(
            row,
            "platform_revision_name",
            classify_missing=True,
        )
        if _REVISION_NAME.fullmatch(platform_revision_name) is None:
            raise ValueError("runtime call telemetry platform revision name is invalid")
        platform_replica_name = _required_text(
            row,
            "platform_replica_name",
            classify_missing=True,
        )
        if _REPLICA_NAME.fullmatch(platform_replica_name) is None:
            raise ValueError("runtime call telemetry platform replica name is invalid")
        source_container_group_id = _required_text(
            row,
            "source_container_group_id",
            classify_missing=True,
        )
        source_container_id = _required_text(
            row,
            "source_container_id",
            classify_missing=True,
        )
        source_platform_timestamp = _required_text(
            row,
            "source_platform_timestamp",
            classify_missing=True,
        )
        caller_name = _validate_container_app_resource_id(
            caller_arm_id,
            field_name="caller_resource_id",
        )
        target_name = _validate_container_app_resource_id(
            target_arm_id,
            field_name="target_resource_id",
        )
        if caller_arm_id.casefold() == target_arm_id.casefold():
            raise ValueError("runtime call caller and target Resource IDs MUST be distinct")
        endpoint_name = caller_name if endpoint_role == "caller" else target_name
        endpoint_arm_id = caller_arm_id if endpoint_role == "caller" else target_arm_id
        platform_resource_id = _required_text(
            row,
            "platform_resource_id",
            classify_missing=True,
        )
        _validate_container_app_resource_id(
            platform_resource_id,
            field_name="platform_resource_id",
        )
        if endpoint_arm_id.casefold() != platform_resource_id.casefold():
            raise ValueError("runtime call Resource ID does not match platform source identity")
        if endpoint_name.casefold() != platform_name.casefold():
            raise ValueError("runtime call Resource ID does not match platform evidence")
        observed_at = _required_datetime(row, "observed_at")
        return _EndpointWitness(
            observation_id=observation_id,
            endpoint_role=endpoint_role,
            caller_arm_id=caller_arm_id,
            target_arm_id=target_arm_id,
            platform_revision_name=platform_revision_name,
            platform_replica_name=platform_replica_name,
            observed_at=observed_at,
            evidence_ref=_digest(
                {
                    "endpoint_role": endpoint_role,
                    "observation_id": observation_id,
                    "observed_at": observed_at.astimezone(UTC).isoformat(),
                    "platform_name": platform_name,
                    "platform_resource_id": platform_resource_id,
                    "platform_revision_name": platform_revision_name,
                    "platform_replica_name": platform_replica_name,
                    "source_container_group_id": source_container_group_id,
                    "source_container_id": source_container_id,
                    "source_platform_timestamp": source_platform_timestamp,
                }
            ),
        )

    def _envelope(
        self,
        *,
        caller: _EndpointWitness,
        target: _EndpointWitness,
        recorded_at: datetime,
    ) -> RuntimeCallTelemetryEnvelope:
        if (
            caller.observation_id != target.observation_id
            or caller.caller_arm_id != target.caller_arm_id
            or caller.target_arm_id != target.target_arm_id
        ):
            raise ValueError("runtime call endpoint witnesses MUST bind the same observation")
        caller_graph_id = to_neutral_id(caller.caller_arm_id)
        target_graph_id = to_neutral_id(caller.target_arm_id)
        observed_at = max(caller.observed_at, target.observed_at)
        return RuntimeCallTelemetryEnvelope(
            observation_id=caller.observation_id,
            caller_resource_ids=(caller_graph_id,),
            target_resource_ids=(target_graph_id,),
            scope_ref=self._scope_ref,
            observed_at=observed_at,
            evidence_cutoff=observed_at,
            recorded_at=recorded_at,
            freshness_ceiling_seconds=self._freshness_ceiling_seconds,
            source_identity=self._source_identity,
            source_revision=self._source_revision,
            evidence_ref=_digest(
                {
                    "caller_evidence_ref": caller.evidence_ref,
                    "caller_resource_id": caller.caller_arm_id,
                    "caller_graph_id": caller_graph_id,
                    "observation_id": caller.observation_id,
                    "observed_at": observed_at.astimezone(UTC).isoformat(),
                    "target_evidence_ref": target.evidence_ref,
                    "target_resource_id": caller.target_arm_id,
                    "target_graph_id": target_graph_id,
                }
            ),
        )


def _required_text(row: Mapping[str, Any], field: str, *, classify_missing: bool = False) -> str:
    value = row.get(field)
    if classify_missing and field not in row:
        raise KeyError(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"runtime call telemetry {field} MUST be bounded non-empty text")
    return value.strip()


def _required_datetime(row: Mapping[str, Any], field: str) -> datetime:
    if field not in row:
        raise KeyError(field)
    value = row.get(field)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"runtime call telemetry {field} MUST be RFC 3339") from exc
    else:
        raise ValueError(f"runtime call telemetry {field} MUST be RFC 3339")
    if parsed.tzinfo is None:
        raise ValueError(f"runtime call telemetry {field} MUST be timezone-aware")
    return parsed


def _required_digest(row: Mapping[str, Any], field: str) -> str:
    value = _required_text(row, field, classify_missing=True)
    if not _is_digest(value):
        raise ValueError(f"runtime call telemetry {field} MUST be canonical SHA-256")
    return value


def _required_false(row: Mapping[str, Any], field: str) -> None:
    if row.get(field) is not False:
        raise ValueError(f"runtime call telemetry {field} MUST be false")


def _validate_container_app_resource_id(value: str, *, field_name: str) -> str:
    segments = value.split("/")
    if (
        len(segments) != 9
        or segments[0] != ""
        or segments[1].casefold() != "subscriptions"
        or not segments[2]
        or segments[3].casefold() != "resourcegroups"
        or not segments[4]
        or segments[5].casefold() != "providers"
        or f"{segments[6]}/{segments[7]}".casefold() != _CONTAINER_APP_PROVIDER_TYPE
        or not segments[8]
    ):
        raise ValueError(f"runtime call telemetry {field_name} MUST identify a Container App")
    return segments[8]


def _record_order(record: RuntimeCallTelemetryRecord) -> tuple[datetime, str, str]:
    return (
        record.envelope.observed_at,
        record.envelope.observation_id,
        record.envelope.evidence_ref,
    )


def _witness_order(witness: _EndpointWitness) -> tuple[datetime, str]:
    return witness.observed_at, witness.evidence_ref


def _digest(body: object) -> str:
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "AzureContainerAppRevisionVerifier",
    "AzureMonitorRuntimeCallAuthenticator",
    "AzureMonitorRuntimeCallContextProvider",
    "AzureRuntimeCallTelemetrySource",
    "RUNTIME_CALL_TELEMETRY_KQL",
    "RuntimeCallTelemetryContextProvider",
    "RuntimeCallEndpointIdentityVerifier",
]
