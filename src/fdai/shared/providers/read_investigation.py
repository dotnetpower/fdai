"""Provider-neutral contracts for bounded read investigations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.providers.tool import ToolCallReceipt

_MAX_ID = 256
_MAX_LABEL = 512
_MAX_CANDIDATES = 8
_MAX_RECORDS = 64


class ReadInvestigationIntent(StrEnum):
    RESOURCE_STATE = "resource_state"
    CHANGE_ATTRIBUTION = "change_attribution"
    RESOURCE_CHANGE_HISTORY = "resource_change_history"
    PLATFORM_HEALTH = "platform_health"
    GUEST_SHUTDOWN = "guest_shutdown"
    NETWORK_SECURITY = "network_security"
    NETWORK_PEERING = "network_peering"


class ReadToolId(StrEnum):
    RESOLVE_RESOURCE = "resolve_resource"
    GET_RESOURCE_STATE = "get_resource_state"
    QUERY_RESOURCE_ACTIVITY = "query_resource_activity"
    QUERY_RESOURCE_HEALTH = "query_resource_health"
    QUERY_GUEST_SHUTDOWN_EVENTS = "query_guest_shutdown_events"
    QUERY_NETWORK_SECURITY = "query_network_security"
    QUERY_NETWORK_PEERINGS = "query_network_peerings"


class ResourceResolutionStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class EvidenceStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NONE = "none"
    UNAVAILABLE = "unavailable"


class EvidenceFreshness(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    STALE = "stale"


class ActorKind(StrEnum):
    USER = "user"
    SERVICE_PRINCIPAL = "service_principal"
    MANAGED_IDENTITY = "managed_identity"
    PLATFORM = "platform"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResourceSelector:
    name: str
    scope_ref: str
    resource_type: str | None = None
    resource_group: str | None = None

    def __post_init__(self) -> None:
        _label("resource selector name", self.name)
        _identifier("resource selector scope_ref", self.scope_ref)
        if self.resource_type is not None:
            _identifier("resource selector resource_type", self.resource_type)
        if self.resource_group is not None:
            _label("resource selector resource_group", self.resource_group)


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    resource_ref: str
    scope_ref: str
    name: str
    resource_type: str
    resource_group: str | None = None

    def __post_init__(self) -> None:
        _identifier("resolved resource_ref", self.resource_ref)
        _identifier("resolved scope_ref", self.scope_ref)
        _label("resolved resource name", self.name)
        _identifier("resolved resource_type", self.resource_type)
        if self.resource_group is not None:
            _label("resolved resource_group", self.resource_group)


@dataclass(frozen=True, slots=True)
class ResourceCandidate:
    resource_ref: str
    name: str
    resource_type: str
    resource_group: str | None = None

    def __post_init__(self) -> None:
        _identifier("candidate resource_ref", self.resource_ref)
        _label("candidate name", self.name)
        _identifier("candidate resource_type", self.resource_type)
        if self.resource_group is not None:
            _label("candidate resource_group", self.resource_group)


@dataclass(frozen=True, slots=True)
class ResourceResolution:
    status: ResourceResolutionStatus
    resource: ResolvedResource | None = None
    candidates: tuple[ResourceCandidate, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.detail is not None:
            _label("resolution detail", self.detail)
        if len(self.candidates) > _MAX_CANDIDATES:
            raise ValueError(f"resource candidates MUST contain <= {_MAX_CANDIDATES} values")
        refs = tuple(candidate.resource_ref for candidate in self.candidates)
        if len(set(refs)) != len(refs):
            raise ValueError("resource candidates MUST be unique")
        if self.status is ResourceResolutionStatus.MATCHED:
            if self.resource is None or self.candidates:
                raise ValueError("matched resolution requires one resource and no candidates")
        elif self.status is ResourceResolutionStatus.AMBIGUOUS:
            if self.resource is not None or len(self.candidates) < 2:
                raise ValueError("ambiguous resolution requires at least two candidates")
        elif self.resource is not None or self.candidates:
            raise ValueError("not_found/unavailable resolution cannot carry resources")


@dataclass(frozen=True, slots=True)
class ReadEvidenceRecord:
    occurred_at: datetime
    status: str
    operation_kind: str | None = None
    actor_ref: str | None = None
    actor_kind: ActorKind | None = None
    correlation_ref: str | None = None
    state: str | None = None
    health_kind: str | None = None
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _aware("evidence occurred_at", self.occurred_at)
        _identifier("evidence status", self.status)
        for name, value in (
            ("operation_kind", self.operation_kind),
            ("actor_ref", self.actor_ref),
            ("correlation_ref", self.correlation_ref),
            ("state", self.state),
            ("health_kind", self.health_kind),
        ):
            if value is not None:
                _identifier(f"evidence {name}", value)
        if len(self.details) > 24:
            raise ValueError("evidence record details MUST contain <= 24 values")
        detail_names = tuple(name for name, _ in self.details)
        if len(set(detail_names)) != len(detail_names):
            raise ValueError("evidence record detail names MUST be unique")
        for name, value in self.details:
            _identifier("evidence detail name", name)
            _label("evidence detail value", value)
        if all(value is None for value in (self.operation_kind, self.state, self.health_kind)) and (
            not self.details
        ):
            raise ValueError(
                "evidence record requires operation_kind, state, health_kind, or details"
            )
        if (self.actor_ref is None) != (self.actor_kind is None):
            raise ValueError("actor_ref and actor_kind MUST be set together")


@dataclass(frozen=True, slots=True)
class ReadEvidenceEnvelope:
    status: EvidenceStatus
    authority: str
    resource_ref: str
    observed_at: datetime
    freshness: EvidenceFreshness
    truncated: bool
    records: tuple[ReadEvidenceRecord, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier("evidence authority", self.authority)
        _identifier("evidence resource_ref", self.resource_ref)
        _aware("evidence observed_at", self.observed_at)
        if len(self.records) > _MAX_RECORDS:
            raise ValueError(f"evidence records MUST contain <= {_MAX_RECORDS} values")
        if len(self.evidence_refs) > _MAX_RECORDS:
            raise ValueError(f"evidence_refs MUST contain <= {_MAX_RECORDS} values")
        for ref in self.evidence_refs:
            _identifier("evidence_ref", ref)
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs MUST be unique")
        if self.status is EvidenceStatus.MATCHED and not self.records:
            raise ValueError("matched evidence requires at least one record")
        if self.status is not EvidenceStatus.MATCHED and self.records:
            raise ValueError("non-matched evidence cannot carry records")


@dataclass(frozen=True, slots=True)
class ReadToolLimits:
    timeout_seconds: float
    max_results: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("read tool timeout_seconds MUST be in [0.1, 120]")
        if not 1 <= self.max_results <= _MAX_RECORDS:
            raise ValueError(f"read tool max_results MUST be in [1, {_MAX_RECORDS}]")
        if not 1_024 <= self.max_output_bytes <= 1_000_000:
            raise ValueError("read tool max_output_bytes MUST be in [1024, 1000000]")


@dataclass(frozen=True, slots=True)
class ResourceResolutionAttempt:
    resolution: ResourceResolution
    receipt: ToolCallReceipt

    def __post_init__(self) -> None:
        if self.receipt.tool_id != ReadToolId.RESOLVE_RESOURCE.value:
            raise ValueError("resolution receipt MUST identify resolve_resource")


@dataclass(frozen=True, slots=True)
class ReadEvidenceAttempt:
    tool_id: ReadToolId
    evidence: ReadEvidenceEnvelope
    receipt: ToolCallReceipt

    def __post_init__(self) -> None:
        if self.tool_id is ReadToolId.RESOLVE_RESOURCE:
            raise ValueError("evidence attempts cannot use resolve_resource")
        if self.receipt.tool_id != self.tool_id.value:
            raise ValueError("evidence receipt tool_id MUST match the attempted tool")


@dataclass(frozen=True, slots=True)
class ReadLatencySample:
    tool_id: ReadToolId
    transport: str
    operation_class: str
    succeeded: bool
    queue_duration_ms: int
    execution_duration_ms: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        _identifier("latency transport", self.transport)
        _identifier("latency operation_class", self.operation_class)
        if min(self.queue_duration_ms, self.execution_duration_ms) < 0:
            raise ValueError("latency durations MUST be non-negative")
        _aware("latency recorded_at", self.recorded_at)

    @property
    def total_duration_ms(self) -> int:
        return self.queue_duration_ms + self.execution_duration_ms


@runtime_checkable
class ReadLatencyProfileStore(Protocol):
    async def append(self, sample: ReadLatencySample) -> None: ...

    async def recent(
        self,
        *,
        tool_id: ReadToolId,
        transport: str,
        operation_class: str,
        limit: int,
    ) -> tuple[ReadLatencySample, ...]: ...


@runtime_checkable
class ReadInvestigationProvider(Protocol):
    @property
    def transport(self) -> str: ...

    async def resolve_resource(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> ResourceResolutionAttempt: ...

    async def get_resource_state(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...

    async def query_resource_activity(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...

    async def query_resource_health(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...

    async def query_guest_shutdown_events(
        self, resource: ResolvedResource, *, lookback_seconds: int, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...

    async def query_network_security(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...

    async def query_network_peerings(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt: ...


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _label(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_LABEL or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be bounded text")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "ActorKind",
    "EvidenceFreshness",
    "EvidenceStatus",
    "ReadEvidenceEnvelope",
    "ReadEvidenceAttempt",
    "ReadEvidenceRecord",
    "ReadInvestigationIntent",
    "ReadInvestigationProvider",
    "ReadLatencyProfileStore",
    "ReadLatencySample",
    "ReadToolId",
    "ReadToolLimits",
    "ResolvedResource",
    "ResourceCandidate",
    "ResourceResolution",
    "ResourceResolutionAttempt",
    "ResourceResolutionStatus",
    "ResourceSelector",
]
