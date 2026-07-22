from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fdai.core.read_investigation import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationService,
    plan_read_investigation,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
    ReadLatencySample,
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

NOW = datetime(2026, 7, 22, tzinfo=UTC)


class _LatencyStore:
    def __init__(self) -> None:
        self.samples: list[ReadLatencySample] = []

    async def append(self, sample: ReadLatencySample) -> None:
        self.samples.append(sample)

    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]:
        del tool_id, transport, operation_class
        return tuple(self.samples[-limit:])


class _Provider:
    transport = "rest"

    def __init__(self, resolution: ResourceResolution) -> None:
        self.resolution = resolution
        self.calls: list[ReadToolId] = []
        self.statuses: dict[ReadToolId, EvidenceStatus] = {}
        self.raise_for: set[ReadToolId] = set()

    async def resolve_resource(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> ResourceResolutionAttempt:
        del selector, limits
        self.calls.append(ReadToolId.RESOLVE_RESOURCE)
        return ResourceResolutionAttempt(
            self.resolution,
            _receipt(ReadToolId.RESOLVE_RESOURCE, "resource_resolution"),
        )

    async def get_resource_state(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del limits
        return self._attempt(ReadToolId.GET_RESOURCE_STATE, resource)

    async def query_resource_activity(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._attempt(ReadToolId.QUERY_RESOURCE_ACTIVITY, resource)

    async def query_resource_health(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._attempt(ReadToolId.QUERY_RESOURCE_HEALTH, resource)

    async def query_guest_shutdown_events(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return self._attempt(ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS, resource)

    async def query_network_security(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del limits
        return self._attempt(ReadToolId.QUERY_NETWORK_SECURITY, resource)

    async def query_network_peerings(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del limits
        return self._attempt(ReadToolId.QUERY_NETWORK_PEERINGS, resource)

    def _attempt(self, tool_id: ReadToolId, resource: ResolvedResource) -> ReadEvidenceAttempt:
        self.calls.append(tool_id)
        if tool_id in self.raise_for:
            raise RuntimeError("raw provider failure MUST NOT escape")
        status = self.statuses.get(tool_id, EvidenceStatus.NONE)
        records = (
            (
                ReadEvidenceRecord(
                    occurred_at=NOW,
                    status="succeeded",
                    operation_kind="deallocate",
                ),
            )
            if status is EvidenceStatus.MATCHED
            else ()
        )
        operation_class = {
            ReadToolId.GET_RESOURCE_STATE: "resource_state",
            ReadToolId.QUERY_RESOURCE_ACTIVITY: "control_plane_activity",
            ReadToolId.QUERY_RESOURCE_HEALTH: "platform_health",
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: "guest_shutdown",
            ReadToolId.QUERY_NETWORK_SECURITY: "network_security",
            ReadToolId.QUERY_NETWORK_PEERINGS: "network_peering",
        }[tool_id]
        return ReadEvidenceAttempt(
            tool_id=tool_id,
            evidence=ReadEvidenceEnvelope(
                status=status,
                authority=operation_class,
                resource_ref=resource.resource_ref,
                observed_at=NOW,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=records,
                evidence_refs=(f"evidence:{tool_id.value}",) if records else (),
            ),
            receipt=_receipt(tool_id, operation_class, result_count=len(records)),
        )


class _ParallelProvider(_Provider):
    def __init__(self, resolution: ResourceResolution) -> None:
        super().__init__(resolution)
        self.active = 0
        self.max_active = 0
        self._release = asyncio.Event()

    async def query_resource_activity(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return await self._concurrent_attempt(ReadToolId.QUERY_RESOURCE_ACTIVITY, resource)

    async def query_resource_health(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return await self._concurrent_attempt(ReadToolId.QUERY_RESOURCE_HEALTH, resource)

    async def query_guest_shutdown_events(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del lookback_seconds, limits
        return await self._concurrent_attempt(
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
            resource,
        )

    async def _concurrent_attempt(
        self,
        tool_id: ReadToolId,
        resource: ResolvedResource,
    ) -> ReadEvidenceAttempt:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active == 3:
            self._release.set()
        try:
            await asyncio.wait_for(self._release.wait(), timeout=0.5)
            return self._attempt(tool_id, resource)
        finally:
            self.active -= 1


def _resource(scope_ref: str = "scope:allowed") -> ResolvedResource:
    return ResolvedResource(
        resource_ref="resource:one",
        scope_ref=scope_ref,
        name="vm-01",
        resource_type="compute.vm",
        resource_group="rg-example",
    )


def _request(intent: ReadInvestigationIntent) -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref="principal:one",
        conversation_ref="conversation:one",
        correlation_ref="correlation:one",
        intent=intent,
        selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(),
        idempotency_key="request:one",
        created_at=NOW,
    )


def _receipt(
    tool_id: ReadToolId, operation_class: str, *, result_count: int = 0
) -> ToolCallReceipt:
    return ToolCallReceipt(
        outcome=ToolCallOutcome.SUCCEEDED,
        receipt_ref=f"receipt:{tool_id.value}",
        tool_id=tool_id.value,
        transport="rest",
        operation_class=operation_class,
        execution_duration_ms=10,
        result_count=result_count,
        recorded_at=NOW,
        trace_ref="correlation:one",
    )


async def test_ambiguous_resolution_stops_before_history_query() -> None:
    candidates = tuple(
        ResourceCandidate(
            resource_ref=f"resource:{index}",
            name="vm-01",
            resource_type="compute.vm",
            resource_group=f"rg-{index}",
        )
        for index in range(2)
    )
    provider = _Provider(
        ResourceResolution(ResourceResolutionStatus.AMBIGUOUS, candidates=candidates)
    )
    result = await ReadInvestigationService(provider, clock=lambda: NOW).execute(
        plan_read_investigation(_request(ReadInvestigationIntent.CHANGE_ATTRIBUTION))
    )
    assert result.outcome is ReadInvestigationOutcome.AMBIGUOUS
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE]
    assert result.progress_kinds[-1] == "investigation.completed"


async def test_scope_widening_fails_closed_before_history_query() -> None:
    provider = _Provider(
        ResourceResolution(ResourceResolutionStatus.MATCHED, resource=_resource("scope:other"))
    )
    result = await ReadInvestigationService(provider, clock=lambda: NOW).execute(
        plan_read_investigation(_request(ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY))
    )
    assert result.outcome is ReadInvestigationOutcome.UNAVAILABLE
    assert provider.calls == [ReadToolId.RESOLVE_RESOURCE]
    assert result.receipts[0].outcome is ToolCallOutcome.FAILED


async def test_attribution_keeps_activity_guest_and_health_evidence_separate() -> None:
    provider = _Provider(ResourceResolution(ResourceResolutionStatus.MATCHED, resource=_resource()))
    provider.statuses[ReadToolId.QUERY_RESOURCE_ACTIVITY] = EvidenceStatus.MATCHED
    provider.statuses[ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS] = EvidenceStatus.UNAVAILABLE
    latency = _LatencyStore()
    result = await ReadInvestigationService(
        provider,
        clock=lambda: NOW,
        latency_store=latency,
    ).execute(plan_read_investigation(_request(ReadInvestigationIntent.CHANGE_ATTRIBUTION)))
    assert result.outcome is ReadInvestigationOutcome.PARTIAL
    assert [item.authority for item in result.evidence] == [
        "control_plane_activity",
        "guest_shutdown",
        "platform_health",
    ]
    assert len(result.receipts) == 4
    assert len(latency.samples) == 4
    assert sum(not sample.succeeded for sample in latency.samples) == 0


async def test_attribution_queries_independent_evidence_sources_in_parallel() -> None:
    provider = _ParallelProvider(
        ResourceResolution(ResourceResolutionStatus.MATCHED, resource=_resource())
    )

    result = await ReadInvestigationService(provider, clock=lambda: NOW).execute(
        plan_read_investigation(_request(ReadInvestigationIntent.CHANGE_ATTRIBUTION))
    )

    assert provider.max_active == 3
    assert [item.authority for item in result.evidence] == [
        "control_plane_activity",
        "guest_shutdown",
        "platform_health",
    ]


def test_parallel_evidence_limit_is_bounded() -> None:
    provider = _Provider(ResourceResolution(ResourceResolutionStatus.MATCHED, resource=_resource()))
    for invalid in (0, 5):
        try:
            ReadInvestigationService(provider, max_parallel_evidence=invalid)
        except ValueError as exc:
            assert "max_parallel_evidence" in str(exc)
        else:  # pragma: no cover - assertion branch
            raise AssertionError("invalid parallel evidence limit was accepted")


async def test_provider_failure_emits_bounded_failed_receipt() -> None:
    provider = _Provider(ResourceResolution(ResourceResolutionStatus.MATCHED, resource=_resource()))
    provider.raise_for.add(ReadToolId.QUERY_RESOURCE_ACTIVITY)
    result = await ReadInvestigationService(provider, clock=lambda: NOW).execute(
        plan_read_investigation(_request(ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY))
    )
    assert result.outcome is ReadInvestigationOutcome.UNAVAILABLE
    assert result.evidence[0].status is EvidenceStatus.UNAVAILABLE
    assert result.receipts[-1].outcome is ToolCallOutcome.FAILED
    assert result.receipts[-1].detail == "provider attempt unavailable"
