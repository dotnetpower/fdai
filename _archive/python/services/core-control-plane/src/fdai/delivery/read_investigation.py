"""Bounded read-investigation adapter over promoted inventory projections."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceLimitationKind,
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

InventoryContextReader = Callable[[str], Awaitable[Mapping[str, Any] | None]]


class InventoryGraphReader(Protocol):
    """Read one bounded projection of the promoted inventory generation."""

    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> Mapping[str, Any]: ...


class InventoryReadInvestigationProvider:
    """Serve exact resource-state reads from the promoted inventory snapshot.

    The adapter never reads the ontology candidate graph. Unsupported evidence
    tools return an explicit unavailable envelope instead of inventing data.
    """

    transport = "promoted_inventory"

    def __init__(
        self,
        *,
        graph_reader: InventoryGraphReader,
        context_reader: InventoryContextReader,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._graph_reader = graph_reader
        self._context_reader = context_reader
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic

    async def resolve_resource(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> ResourceResolutionAttempt:
        started = self._monotonic()
        graph = await self._graph_reader(None, 1, (), limit=limits.max_results)
        resources = graph.get("resources")
        if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes)):
            resolution = ResourceResolution(
                status=ResourceResolutionStatus.UNAVAILABLE,
                detail="promoted inventory projection is unavailable",
            )
        else:
            matches = tuple(
                candidate
                for raw in resources
                if isinstance(raw, Mapping)
                and (candidate := _candidate(raw)) is not None
                and _matches_selector(candidate, selector)
            )
            if len(matches) == 1:
                candidate = matches[0]
                resolution = ResourceResolution(
                    status=ResourceResolutionStatus.MATCHED,
                    resource=ResolvedResource(
                        resource_ref=candidate.resource_ref,
                        scope_ref=selector.scope_ref,
                        name=candidate.name,
                        resource_type=candidate.resource_type,
                        resource_group=candidate.resource_group,
                    ),
                )
            elif len(matches) > 8:
                resolution = ResourceResolution(
                    status=ResourceResolutionStatus.UNAVAILABLE,
                    detail="resource resolution exceeded its candidate bound",
                )
            elif len(matches) > 1:
                resolution = ResourceResolution(
                    status=ResourceResolutionStatus.AMBIGUOUS,
                    candidates=matches,
                    detail="multiple exact resource identities matched",
                )
            elif graph.get("truncated") is True:
                resolution = ResourceResolution(
                    status=ResourceResolutionStatus.UNAVAILABLE,
                    detail="promoted inventory projection is truncated",
                )
            else:
                resolution = ResourceResolution(status=ResourceResolutionStatus.NOT_FOUND)
        return ResourceResolutionAttempt(
            resolution=resolution,
            receipt=self._receipt(
                ReadToolId.RESOLVE_RESOURCE,
                "resource_resolution",
                started=started,
                result_count=1 if resolution.status is ResourceResolutionStatus.MATCHED else 0,
            ),
        )

    async def get_resource_state(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del limits
        started = self._monotonic()
        graph = await self._graph_reader(
            None,
            1,
            (),
            root=resource.resource_ref,
            limit=2,
        )
        context = await self._context_reader(resource.resource_ref)
        observed_at = _timestamp(graph.get("snapshot_at"), fallback=self._clock())
        freshness = (
            EvidenceFreshness.LIVE if graph.get("freshness") == "fresh" else EvidenceFreshness.STALE
        )
        state = _resource_state(context)
        record = (
            ReadEvidenceRecord(
                occurred_at=observed_at,
                status="observed",
                state=state,
            )
            if state is not None
            else None
        )
        snapshot_id = str(graph.get("snapshot_id") or "unavailable")
        evidence = ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED if record is not None else EvidenceStatus.NONE,
            authority="inventory.resource_state",
            resource_ref=resource.resource_ref,
            observed_at=observed_at,
            freshness=freshness,
            truncated=False,
            records=(record,) if record is not None else (),
            evidence_refs=(f"inventory-snapshot:{snapshot_id}",) if record is not None else (),
        )
        return ReadEvidenceAttempt(
            tool_id=ReadToolId.GET_RESOURCE_STATE,
            evidence=evidence,
            receipt=self._receipt(
                ReadToolId.GET_RESOURCE_STATE,
                "resource_state",
                started=started,
                result_count=len(evidence.records),
            ),
        )

    async def query_resource_activity(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._unavailable(ReadToolId.QUERY_RESOURCE_ACTIVITY, resource)

    async def query_resource_health(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._unavailable(ReadToolId.QUERY_RESOURCE_HEALTH, resource)

    async def query_guest_shutdown_events(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._unavailable(ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS, resource)

    async def query_network_security(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del limits
        return self._unavailable(ReadToolId.QUERY_NETWORK_SECURITY, resource)

    async def query_network_peerings(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        del limits
        return self._unavailable(ReadToolId.QUERY_NETWORK_PEERINGS, resource)

    def _unavailable(
        self,
        tool_id: ReadToolId,
        resource: ResolvedResource,
    ) -> ReadEvidenceAttempt:
        observed_at = self._clock()
        return ReadEvidenceAttempt(
            tool_id=tool_id,
            evidence=ReadEvidenceEnvelope(
                status=EvidenceStatus.UNAVAILABLE,
                authority="inventory.unsupported_read",
                resource_ref=resource.resource_ref,
                observed_at=observed_at,
                freshness=EvidenceFreshness.CACHED,
                truncated=False,
                records=(),
                evidence_refs=(),
                limitations=(EvidenceLimitationKind.SOURCE_UNAVAILABLE,),
            ),
            receipt=self._receipt(tool_id, "unsupported_read", started=self._monotonic()),
        )

    def _receipt(
        self,
        tool_id: ReadToolId,
        operation_class: str,
        *,
        started: float,
        result_count: int = 0,
    ) -> ToolCallReceipt:
        recorded_at = self._clock()
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=f"inventory-read:{tool_id.value}:{recorded_at.isoformat()}",
            detail="promoted inventory read completed",
            tool_id=tool_id.value,
            transport=self.transport,
            operation_class=operation_class,
            execution_duration_ms=max(0, round((self._monotonic() - started) * 1_000)),
            result_count=result_count,
            recorded_at=recorded_at,
        )


def _candidate(raw: Mapping[str, Any]) -> ResourceCandidate | None:
    resource_ref = raw.get("id")
    name = raw.get("name")
    resource_type = raw.get("type")
    if not isinstance(resource_ref, str) or not resource_ref.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(resource_type, str) or not resource_type.strip():
        return None
    props = raw.get("props")
    group = props.get("resourceGroup") if isinstance(props, Mapping) else None
    return ResourceCandidate(
        resource_ref=resource_ref,
        name=name,
        resource_type=resource_type,
        resource_group=group if isinstance(group, str) and group else None,
    )


def _matches_selector(candidate: ResourceCandidate, selector: ResourceSelector) -> bool:
    identity_matches = candidate.name.casefold() == selector.name.casefold() or (
        candidate.resource_ref.casefold() == selector.name.casefold()
    )
    return (
        identity_matches
        and (selector.resource_type is None or candidate.resource_type == selector.resource_type)
        and (selector.resource_group is None or candidate.resource_group == selector.resource_group)
    )


def _resource_state(context: Mapping[str, Any] | None) -> str | None:
    if context is None:
        return None
    props = context.get("props")
    if not isinstance(props, Mapping):
        return None
    value = props.get("state") or props.get("status")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _timestamp(value: object, *, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return parsed if parsed.tzinfo is not None else fallback


__all__ = ["InventoryGraphReader", "InventoryReadInvestigationProvider"]
