"""Azure raw projections normalized into provider-neutral read evidence."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

from fdai.delivery.azure.read_investigation.transport import AzureReadTransport, AzureRow
from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
    ResourceCandidate,
    ResourceResolution,
    ResourceResolutionAttempt,
    ResourceResolutionStatus,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt

Clock = Callable[[], datetime]
Monotonic = Callable[[], float]

_MAX_BINDINGS = 1_024
_ACTOR_KINDS = {
    "user": ActorKind.USER,
    "serviceprincipal": ActorKind.SERVICE_PRINCIPAL,
    "service_principal": ActorKind.SERVICE_PRINCIPAL,
    "managedidentity": ActorKind.MANAGED_IDENTITY,
    "managed_identity": ActorKind.MANAGED_IDENTITY,
    "platform": ActorKind.PLATFORM,
}


class AzureReadInvestigationProvider:
    """Normalize one registered Azure transport without exposing raw output."""

    def __init__(
        self,
        transport: AzureReadTransport,
        *,
        clock: Clock | None = None,
        monotonic: Monotonic | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic
        self._provider_refs: OrderedDict[str, str] = OrderedDict()

    @property
    def transport(self) -> str:
        return self._transport.transport_id

    async def resolve_resource(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> ResourceResolutionAttempt:
        started = self._monotonic()
        rows = await self._transport.resolve_resources(selector, limits=limits)
        filtered = _matching_resources(rows, selector)
        candidates = tuple(
            ResourceCandidate(
                resource_ref=_opaque("resource", _required(row, "id")),
                name=_required(row, "name"),
                resource_type=_required(row, "type"),
                resource_group=_optional(row, "resource_group"),
            )
            for row in filtered[: limits.max_results]
        )
        truncated = len(filtered) > limits.max_results
        if len(filtered) > 1 and limits.max_results < 2:
            resolution = ResourceResolution(
                ResourceResolutionStatus.UNAVAILABLE,
                detail="resource candidate cap cannot represent ambiguity",
            )
            truncated = True
        elif not candidates:
            resolution = ResourceResolution(ResourceResolutionStatus.NOT_FOUND)
        elif len(candidates) > 1:
            resolution = ResourceResolution(
                ResourceResolutionStatus.AMBIGUOUS,
                candidates=candidates[:8],
                detail="multiple resources matched the bounded selector",
            )
            truncated = truncated or len(candidates) > 8
        else:
            row = filtered[0]
            candidate = candidates[0]
            resource = ResolvedResource(
                resource_ref=candidate.resource_ref,
                scope_ref=selector.scope_ref,
                name=candidate.name,
                resource_type=candidate.resource_type,
                resource_group=candidate.resource_group,
            )
            self._remember(resource.resource_ref, _required(row, "id"))
            resolution = ResourceResolution(
                ResourceResolutionStatus.MATCHED,
                resource=resource,
            )
        return ResourceResolutionAttempt(
            resolution=resolution,
            receipt=self._receipt(
                ReadToolId.RESOLVE_RESOURCE,
                "resource_resolution",
                started=started,
                result_count=len(candidates),
                truncated=truncated,
            ),
        )

    async def get_resource_state(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.GET_RESOURCE_STATE,
            resource,
            fetch=lambda provider_ref: self._transport.get_resource_state(
                provider_ref,
                limits=limits,
            ),
            limits=limits,
        )

    async def query_resource_activity(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.QUERY_RESOURCE_ACTIVITY,
            resource,
            fetch=lambda provider_ref: self._transport.query_resource_activity(
                provider_ref,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
            limits=limits,
        )

    async def query_resource_health(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.QUERY_RESOURCE_HEALTH,
            resource,
            fetch=lambda provider_ref: self._transport.query_resource_health(
                provider_ref,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
            limits=limits,
        )

    async def query_guest_shutdown_events(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
            resource,
            fetch=lambda provider_ref: self._transport.query_guest_shutdown_events(
                provider_ref,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
            limits=limits,
        )

    async def query_network_security(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.QUERY_NETWORK_SECURITY,
            resource,
            fetch=lambda provider_ref: self._transport.query_network_security(
                provider_ref,
                limits=limits,
            ),
            limits=limits,
        )

    async def query_network_peerings(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._evidence(
            ReadToolId.QUERY_NETWORK_PEERINGS,
            resource,
            fetch=lambda provider_ref: self._transport.query_network_peerings(
                provider_ref,
                limits=limits,
            ),
            limits=limits,
        )

    async def _evidence(
        self,
        tool_id: ReadToolId,
        resource: ResolvedResource,
        *,
        fetch: Callable[[str], Awaitable[Sequence[AzureRow]]],
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        provider_ref = self._provider_refs.get(resource.resource_ref)
        if provider_ref is None:
            raise LookupError("resolved resource binding is unavailable")
        started = self._monotonic()
        rows = await fetch(provider_ref)
        records, truncated = _normalize_records(tool_id, rows, limits)
        authority, operation_class = _authority(tool_id)
        evidence = ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED if records else EvidenceStatus.NONE,
            authority=authority,
            resource_ref=resource.resource_ref,
            observed_at=self._clock(),
            freshness=EvidenceFreshness.LIVE,
            truncated=truncated,
            records=records,
            evidence_refs=tuple(_evidence_ref(authority, record) for record in records),
        )
        return ReadEvidenceAttempt(
            tool_id=tool_id,
            evidence=evidence,
            receipt=self._receipt(
                tool_id,
                operation_class,
                started=started,
                result_count=len(records),
                truncated=truncated,
            ),
        )

    def _remember(self, resource_ref: str, provider_ref: str) -> None:
        self._provider_refs[resource_ref] = provider_ref
        self._provider_refs.move_to_end(resource_ref)
        while len(self._provider_refs) > _MAX_BINDINGS:
            self._provider_refs.popitem(last=False)

    def _receipt(
        self,
        tool_id: ReadToolId,
        operation_class: str,
        *,
        started: float,
        result_count: int,
        truncated: bool,
    ) -> ToolCallReceipt:
        recorded_at = self._clock()
        receipt_ref = _opaque(
            "read-receipt",
            f"{tool_id.value}:{self.transport}:{recorded_at.isoformat()}:{result_count}",
        )
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=receipt_ref,
            tool_id=tool_id.value,
            transport=self.transport,
            operation_class=operation_class,
            execution_duration_ms=max(0, round((self._monotonic() - started) * 1_000)),
            result_count=result_count,
            truncated=truncated,
            cache_status="miss",
            recorded_at=recorded_at,
            trace_ref=receipt_ref,
        )


def _matching_resources(rows: Sequence[AzureRow], selector: ResourceSelector) -> list[AzureRow]:
    matches: list[AzureRow] = []
    for row in rows:
        try:
            name = _required(row, "name")
            resource_type = _required(row, "type")
            _required(row, "id")
        except ValueError:
            continue
        if name.casefold() != selector.name.casefold():
            continue
        if selector.resource_type is not None and (
            resource_type.casefold() != selector.resource_type.casefold()
        ):
            continue
        group = _optional(row, "resource_group")
        if selector.resource_group is not None and (
            group is None or group.casefold() != selector.resource_group.casefold()
        ):
            continue
        matches.append(row)
    matches.sort(
        key=lambda row: (
            (_optional(row, "resource_group") or "").casefold(),
            _required(row, "type").casefold(),
            _required(row, "id").casefold(),
        )
    )
    return matches


def _normalize_records(
    tool_id: ReadToolId,
    rows: Sequence[AzureRow],
    limits: ReadToolLimits,
) -> tuple[tuple[ReadEvidenceRecord, ...], bool]:
    records: list[ReadEvidenceRecord] = []
    used_bytes = 0
    truncated = False
    for row in rows:
        if row.get("_truncated") is True:
            truncated = True
            continue
        record = _normalize_record(tool_id, row)
        if record is None:
            continue
        record_bytes = len(repr(record).encode("utf-8"))
        if (
            len(records) >= limits.max_results
            or used_bytes + record_bytes > limits.max_output_bytes
        ):
            truncated = True
            break
        records.append(record)
        used_bytes += record_bytes
    return tuple(records), truncated


def _normalize_record(tool_id: ReadToolId, row: AzureRow) -> ReadEvidenceRecord | None:
    occurred_at = _timestamp(row.get("occurred_at") or row.get("observed_at"))
    if occurred_at is None:
        return None
    status = _normalized_token(row.get("status"), fallback="unknown")
    if tool_id is ReadToolId.GET_RESOURCE_STATE:
        state = _normalized_token(row.get("state"), fallback="unknown")
        return ReadEvidenceRecord(occurred_at=occurred_at, status=status, state=state)
    if tool_id is ReadToolId.QUERY_RESOURCE_ACTIVITY:
        operation = _operation(row.get("operation"))
        if operation is None:
            return None
        caller = row.get("caller")
        actor_ref = _opaque("principal", caller) if isinstance(caller, str) and caller else None
        actor_kind = _ACTOR_KINDS.get(
            str(row.get("caller_kind", "")).replace(" ", "").casefold(),
            ActorKind.UNKNOWN if actor_ref is not None else None,
        )
        correlation = row.get("correlation")
        return ReadEvidenceRecord(
            occurred_at=occurred_at,
            status=status,
            operation_kind=operation,
            actor_ref=actor_ref,
            actor_kind=actor_kind,
            correlation_ref=(
                _opaque("correlation", correlation)
                if isinstance(correlation, str) and correlation
                else None
            ),
        )
    if tool_id is ReadToolId.QUERY_RESOURCE_HEALTH:
        return ReadEvidenceRecord(
            occurred_at=occurred_at,
            status=status,
            health_kind=_normalized_token(row.get("health_kind"), fallback="unknown"),
        )
    if tool_id is ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS:
        return ReadEvidenceRecord(
            occurred_at=occurred_at,
            status=status,
            operation_kind="guest_shutdown",
        )
    if tool_id is ReadToolId.QUERY_NETWORK_SECURITY:
        return ReadEvidenceRecord(
            occurred_at=occurred_at,
            status=status,
            details=_details(
                row,
                (
                    "rule_name",
                    "rule_kind",
                    "direction",
                    "protocol",
                    "source_prefixes",
                    "source_ports",
                    "destination_prefixes",
                    "destination_ports",
                    "priority",
                    "associations",
                ),
            ),
        )
    if tool_id is ReadToolId.QUERY_NETWORK_PEERINGS:
        return ReadEvidenceRecord(
            occurred_at=occurred_at,
            status=status,
            details=_details(
                row,
                (
                    "peering_name",
                    "remote_vnet",
                    "sync_level",
                    "allow_vnet_access",
                    "allow_forwarded_traffic",
                    "allow_gateway_transit",
                    "use_remote_gateways",
                    "remote_address_prefixes",
                    "local_subnets",
                    "remote_subnets",
                ),
            ),
        )
    return None


def _authority(tool_id: ReadToolId) -> tuple[str, str]:
    return {
        ReadToolId.GET_RESOURCE_STATE: ("azure.resource_state", "resource_state"),
        ReadToolId.QUERY_RESOURCE_ACTIVITY: (
            "azure.activity_log",
            "control_plane_activity",
        ),
        ReadToolId.QUERY_RESOURCE_HEALTH: ("azure.resource_health", "platform_health"),
        ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: ("azure.guest_log", "guest_shutdown"),
        ReadToolId.QUERY_NETWORK_SECURITY: (
            "azure.network_security",
            "network_security",
        ),
        ReadToolId.QUERY_NETWORK_PEERINGS: ("azure.network_peering", "network_peering"),
    }[tool_id]


def _details(row: AzureRow, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    details: list[tuple[str, str]] = []
    for name in names:
        raw = row.get(name)
        if isinstance(raw, bool):
            value = str(raw).lower()
        elif isinstance(raw, (str, int)) and not isinstance(raw, bool):
            value = str(raw).strip()
        else:
            continue
        if value:
            details.append((name, value[:512]))
    return tuple(details)


def _operation(raw: object) -> str | None:
    value = str(raw or "").casefold()
    for marker, operation in (
        ("deallocate", "deallocate"),
        ("poweroff", "power_off"),
        ("power off", "power_off"),
        ("restart", "restart"),
        ("start", "start"),
        ("delete", "delete"),
        ("write", "write"),
    ):
        if marker in value:
            return operation
    return None


def _normalized_token(raw: object, *, fallback: str) -> str:
    rendered = str(raw or "").strip().casefold().replace(" ", "_").replace("/", "_")
    filtered = "".join(char for char in rendered if char.isalnum() or char in "_.-")
    return filtered[:128] or fallback


def _timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _required(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Azure projection missing {key}")
    return value


def _optional(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) and value else None


def _opaque(kind: str, raw: object) -> str:
    digest = hashlib.sha256(str(raw).encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


def _evidence_ref(authority: str, record: ReadEvidenceRecord) -> str:
    payload = json.dumps(
        {
            "authority": authority,
            "occurred_at": record.occurred_at.isoformat(),
            "status": record.status,
            "operation_kind": record.operation_kind,
            "actor_ref": record.actor_ref,
            "correlation_ref": record.correlation_ref,
            "state": record.state,
            "health_kind": record.health_kind,
            "details": record.details,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _opaque("evidence", payload)


__all__ = ["AzureReadInvestigationProvider"]
