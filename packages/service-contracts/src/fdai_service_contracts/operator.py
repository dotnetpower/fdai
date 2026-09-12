"""Neutral DTOs and provider protocols for the independent Operator Service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None  # noqa: UP040
JsonValue: TypeAlias = (  # noqa: UP040
    JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]  # noqa: UP040


class OperatorRole(StrEnum):
    """Human roles accepted by the Operator HTTP boundary."""

    READER = "Reader"
    CONTRIBUTOR = "Contributor"
    APPROVER = "Approver"
    OWNER = "Owner"
    BREAK_GLASS = "BreakGlass"


def canonical_ordinary_role(role: OperatorRole | str) -> str:
    """Normalize one ordinary query role and exclude BreakGlass."""
    value = role.value if isinstance(role, OperatorRole) else role
    normalized = value.casefold()
    if normalized not in {"reader", "contributor", "approver", "owner"}:
        raise ValueError("BreakGlass is not a query role")
    return normalized


class OperatorPrincipalKind(StrEnum):
    """Authenticated principal classes accepted by the Operator boundary."""

    HUMAN = "human"
    WORKLOAD = "workload"


@dataclass(frozen=True, slots=True)
class OperatorPrincipal:
    """Verified identity and server-derived Operator roles."""

    subject_id: str
    roles: frozenset[OperatorRole]
    principal_kind: OperatorPrincipalKind = OperatorPrincipalKind.HUMAN
    groups: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise ValueError("operator principal subject_id must be non-empty")
        if len(self.groups) > 64 or any(
            not group.strip() or len(group) > 256 for group in self.groups
        ):
            raise ValueError("operator principal groups must contain at most 64 bounded values")


@dataclass(frozen=True, slots=True)
class AuditQuery:
    """Bounded audit page request passed to an authoritative read model."""

    limit: int
    cursor: str | None = None
    correlation_id: str | None = None
    mode: str | None = None
    tier: str | None = None
    action_kind: str | None = None
    outcome: str | None = None
    vertical: str | None = None
    window_days: int | None = None
    from_seq: int | None = None
    through_seq: int | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 500:
            raise ValueError("audit limit MUST be in [1, 500]")
        if self.mode is not None and self.mode not in {"shadow", "enforce"}:
            raise ValueError("audit mode MUST be shadow or enforce")
        if self.tier is not None and self.tier not in {"t0", "t1", "t2"}:
            raise ValueError("audit tier MUST be t0, t1 or t2")
        for value in (self.action_kind, self.outcome, self.vertical):
            if value is not None and (
                not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value
            ):
                raise ValueError("audit filters MUST be bounded nonempty text")
        if self.window_days is not None and (
            type(self.window_days) is not int or not 1 <= self.window_days <= 999
        ):
            raise ValueError("audit window MUST be in [1, 999] days")
        for sequence in (self.from_seq, self.through_seq):
            if sequence is not None and (
                type(sequence) is not int or not 1 <= sequence <= 9_223_372_036_854_775_807
            ):
                raise ValueError("audit sequence filter MUST be a positive bigint")
        if self.from_seq is not None and self.through_seq is not None:
            if self.from_seq > self.through_seq:
                raise ValueError("audit sequence bounds are reversed")


@dataclass(frozen=True, slots=True)
class BrowserEvidenceQuery:
    """Bound one browser-evidence metadata page request."""

    limit: int

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 500:
            raise ValueError("browser evidence limit must be in [1, 500]")


@dataclass(frozen=True, slots=True)
class HilQueueQuery:
    """Bounded approval queue request with server-authorized detail visibility."""

    limit: int
    search: str | None
    include_details: bool


@dataclass(frozen=True, slots=True)
class IncidentQuery:
    """Bounded incident page request over the durable audit projection."""

    status: Literal["active", "resolved", "all"]
    limit: int
    search: str | None = None
    cursor: str | None = None
    vertical: str | None = None
    severity: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class IncidentAttentionQuery:
    """Durable incident-attention snapshot request for SSE replay."""

    after_seq: int | None
    limit: int


@dataclass(frozen=True, slots=True)
class IncidentAttentionProjection:
    """One durable SSE snapshot with its audit replay sequence."""

    sequence: int
    payload: Mapping[str, JsonValue]

    def to_dict(self) -> JsonObject:
        """Copy the frozen snapshot payload without adding transport metadata."""
        return dict(self.payload)


@dataclass(frozen=True, slots=True)
class AgentActivityQuery:
    """Bound one durable operational activity snapshot request."""

    limit: int

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 500:
            raise ValueError("agent activity limit must be in [1, 500]")


@dataclass(frozen=True, slots=True)
class PageProjection:
    """Opaque-cursor JSON page returned by a service-owned projection adapter."""

    items: tuple[JsonObject, ...]
    next_cursor: str | None

    def to_dict(self) -> JsonObject:
        """Return the stable HTTP page envelope."""
        return {
            "items": [dict(item) for item in self.items],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class IncidentPageProjection:
    """Incident page plus same-snapshot outcome metrics owned by the read model."""

    items: tuple[JsonObject, ...]
    next_cursor: str | None
    metrics: JsonObject

    def to_dict(self) -> JsonObject:
        """Return the stable Incident HTTP envelope with top-level metrics."""
        return {
            "items": [dict(item) for item in self.items],
            "next_cursor": self.next_cursor,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class HilQueueProjection:
    """Approval queue projection with an explicit total and detail level."""

    items: tuple[JsonObject, ...]
    total: int

    def to_dict(self, *, include_details: bool) -> JsonObject:
        """Return the stable queue envelope without leaking unauthorized details."""
        return {
            "items": [dict(item) for item in self.items] if include_details else [],
            "total": self.total,
            "detail_level": "full" if include_details else "count_only",
        }


@dataclass(frozen=True, slots=True)
class JsonProjection:
    """Validated JSON object supplied by one authoritative projection adapter."""

    payload: Mapping[str, JsonValue]

    def to_dict(self) -> JsonObject:
        """Copy the projection into a response-owned JSON object."""
        return dict(self.payload)


@dataclass(frozen=True, slots=True)
class ReadDataSource:
    """Non-probing provenance declaration for one Operator read surface."""

    key: str
    source: str
    routes: tuple[str, ...]
    availability: Literal["available", "unavailable", "unknown"]
    configured: bool
    reachable: bool | None
    authoritative: bool
    durable: bool | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.key.strip()
            or not self.source.strip()
            or not self.routes
            or any(not route.startswith("/") for route in self.routes)
        ):
            raise ValueError("read data source identity and routes must be non-empty")
        if self.availability == "available" and not self.configured:
            raise ValueError("an available read data source must be configured")
        if self.availability == "unavailable" and not self.reason:
            raise ValueError("an unavailable read data source must include a reason")
        if self.availability == "unavailable" and self.reachable is True:
            raise ValueError("an unavailable read data source cannot be reachable")

    def to_dict(self) -> JsonObject:
        """Return the stable source manifest record."""
        return {
            "key": self.key,
            "source": self.source,
            "routes": list(self.routes),
            "availability": self.availability,
            "configured": self.configured,
            "reachable": self.reachable,
            "authoritative": self.authoritative,
            "durable": self.durable,
            "synthetic": False,
            "reason": self.reason,
        }


class OperatorTokenVerifier(Protocol):
    """Verify a bearer token and return trusted claims without resolving roles."""

    def __call__(self, token: str) -> Mapping[str, object]: ...


class OperatorReadModel(Protocol):
    """Read authoritative Operator projections without mutation authority."""

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection: ...

    async def list_audit(self, query: AuditQuery) -> PageProjection: ...

    async def list_browser_evidence(self, query: BrowserEvidenceQuery) -> JsonProjection: ...

    async def dashboard_metrics(self) -> JsonProjection: ...

    async def llm_usage(self, range_start: datetime, range_end: datetime) -> JsonProjection: ...

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection: ...

    async def list_incidents(self, query: IncidentQuery) -> IncidentPageProjection: ...

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection | None: ...

    async def get_rca(self, correlation_id: str) -> JsonProjection | None: ...

    async def get_rule_fire_trace(self, correlation_id: str) -> JsonProjection | None: ...


class AgentActivityReadModel(Protocol):
    """Read durable operational activity without stream or mutation authority."""

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection: ...


__all__ = [
    "AgentActivityQuery",
    "AgentActivityReadModel",
    "AuditQuery",
    "BrowserEvidenceQuery",
    "HilQueueProjection",
    "HilQueueQuery",
    "IncidentAttentionQuery",
    "IncidentAttentionProjection",
    "IncidentPageProjection",
    "IncidentQuery",
    "JsonObject",
    "JsonProjection",
    "JsonScalar",
    "JsonValue",
    "OperatorPrincipal",
    "OperatorReadModel",
    "OperatorRole",
    "OperatorTokenVerifier",
    "PageProjection",
    "ReadDataSource",
]
