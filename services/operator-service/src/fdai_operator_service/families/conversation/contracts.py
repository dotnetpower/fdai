"""Implementation-free contracts for the Operator conversation HTTP family."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from starlette.requests import Request

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

MAX_IDENTIFIER_CHARS = 256
MAX_OPERATION_CHARS = 128
MAX_ROLES = 16
MAX_BODY_BYTES = 1_048_576
MAX_QUERY_BYTES = 8_192
MAX_RESPONSE_BYTES = 16_777_216
MAX_STREAM_EVENT_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class PrincipalScope:
    """Verified human identity and roles used to scope every family operation."""

    subject_id: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _bounded_text("subject_id", self.subject_id, maximum=MAX_IDENTIFIER_CHARS)
        if len(self.roles) > MAX_ROLES:
            raise ValueError(f"roles MUST contain at most {MAX_ROLES} values")
        for role in self.roles:
            _bounded_text("role", role, maximum=64)


@dataclass(frozen=True, slots=True)
class ConversationQuery:
    """Bounded principal-scoped request for an authoritative projection."""

    operation: str
    scope: PrincipalScope
    query: JsonObject = field(default_factory=dict)
    path_params: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _bounded_text("operation", self.operation, maximum=MAX_OPERATION_CHARS)
        _bounded_json("query", self.query, maximum=MAX_QUERY_BYTES)
        _bounded_json("path_params", self.path_params, maximum=MAX_QUERY_BYTES)


@dataclass(frozen=True, slots=True)
class ConversationProposal:
    """Typed outbox record that carries intent but never effect authority."""

    operation: str
    scope: PrincipalScope
    idempotency_key: str
    body: JsonObject = field(default_factory=dict)
    query: JsonObject = field(default_factory=dict)
    path_params: JsonObject = field(default_factory=dict)
    confirmed: bool = False
    cancellation: bool = False

    def __post_init__(self) -> None:
        _bounded_text("operation", self.operation, maximum=MAX_OPERATION_CHARS)
        _bounded_text("idempotency_key", self.idempotency_key, maximum=256)
        _bounded_json("body", self.body, maximum=MAX_BODY_BYTES)
        _bounded_json("query", self.query, maximum=MAX_QUERY_BYTES)
        _bounded_json("path_params", self.path_params, maximum=MAX_QUERY_BYTES)


@dataclass(frozen=True, slots=True)
class ConversationResponse:
    """Bounded HTTP result returned by an injected projection or outbox."""

    body: JsonObject | bytes | None
    status_code: int = 200
    media_type: str = "application/json"
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code MUST be a valid HTTP status")
        _bounded_text("media_type", self.media_type, maximum=128)
        if len(self.headers) > 16:
            raise ValueError("headers MUST contain at most 16 entries")
        for key, value in self.headers:
            _bounded_text("header name", key, maximum=128)
            _bounded_text("header value", value, maximum=2_048, allow_empty=True)
        if isinstance(self.body, bytes):
            if len(self.body) > MAX_RESPONSE_BYTES:
                raise ValueError("binary response exceeds cap")
        elif self.body is not None:
            _bounded_json("response body", self.body, maximum=MAX_RESPONSE_BYTES)


@dataclass(frozen=True, slots=True)
class OutboxReceipt:
    """Durable proposal acknowledgement with a compatibility response envelope."""

    proposal_id: str
    duplicate: bool
    response: ConversationResponse

    def __post_init__(self) -> None:
        _bounded_text("proposal_id", self.proposal_id, maximum=256)


@dataclass(frozen=True, slots=True)
class ConversationStreamRequest:
    """Bounded stream request carrying replay and principal scope."""

    operation: str
    scope: PrincipalScope
    body: JsonObject = field(default_factory=dict)
    query: JsonObject = field(default_factory=dict)
    path_params: JsonObject = field(default_factory=dict)
    after_event_id: str | None = None
    idempotency_key: str | None = None
    proposal_id: str | None = None

    def __post_init__(self) -> None:
        _bounded_text("operation", self.operation, maximum=MAX_OPERATION_CHARS)
        if self.after_event_id is not None:
            _bounded_text("after_event_id", self.after_event_id, maximum=256)
        if self.idempotency_key is not None:
            _bounded_text("idempotency_key", self.idempotency_key, maximum=256)
        if self.proposal_id is not None:
            _bounded_text("proposal_id", self.proposal_id, maximum=256)
        _bounded_json("body", self.body, maximum=MAX_BODY_BYTES)
        _bounded_json("query", self.query, maximum=MAX_QUERY_BYTES)
        _bounded_json("path_params", self.path_params, maximum=MAX_QUERY_BYTES)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One replayable SSE event or an explicit heartbeat."""

    event: str | None
    data: JsonObject = field(default_factory=dict)
    event_id: str | None = None
    retry_ms: int | None = None

    def __post_init__(self) -> None:
        if self.event is not None:
            _single_line("event", self.event, maximum=128)
        if self.event_id is not None:
            _single_line("event_id", self.event_id, maximum=256)
        if self.retry_ms is not None and not 100 <= self.retry_ms <= 60_000:
            raise ValueError("retry_ms MUST be in [100, 60000]")
        _bounded_json("stream event data", self.data, maximum=MAX_STREAM_EVENT_BYTES)


class ConversationAuthorizer(Protocol):
    """Authenticate a request and apply server-owned authorization for an operation."""

    async def authorize(self, request: Request, *, operation: str) -> PrincipalScope: ...


class ConversationProjectionReader(Protocol):
    """Read authoritative principal-scoped conversation projections."""

    async def read(self, query: ConversationQuery) -> ConversationResponse: ...


class ConversationProposalOutbox(Protocol):
    """Persist typed proposals with duplicate suppression and no execution side effect."""

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt: ...


class ConversationEventStream(AsyncIterator[StreamEvent], Protocol):
    """Closeable event iterator so HTTP disconnects cancel upstream observation."""

    async def aclose(self) -> None: ...


class ConversationStreamReader(Protocol):
    """Open principal-scoped replayable event streams."""

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream: ...


class ConversationBoundaryError(Exception):
    """Safe client-visible failure raised by an injected family dependency."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ConversationUnavailableError(ConversationBoundaryError):
    """An authoritative dependency is unavailable, so the request must fail closed."""

    def __init__(self, message: str = "conversation capability is unavailable") -> None:
        super().__init__(503, "unavailable", message)


def _bounded_text(name: str, value: str, *, maximum: int, allow_empty: bool = False) -> None:
    invalid = not isinstance(value, str) or (not allow_empty and not value.strip())
    if invalid or len(value) > maximum:
        qualifier = "bounded" if allow_empty else "non-empty bounded"
        raise ValueError(f"{name} MUST be a {qualifier} string")


def _single_line(name: str, value: str, *, maximum: int) -> None:
    _bounded_text(name, value, maximum=maximum)
    if "\r" in value or "\n" in value:
        raise ValueError(f"{name} MUST be a single line")


def _bounded_json(name: str, value: JsonObject, *, maximum: int) -> None:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} MUST contain valid JSON values") from exc
    if len(encoded) > maximum:
        raise ValueError(f"{name} exceeds cap")


__all__ = [
    "ConversationAuthorizer",
    "ConversationBoundaryError",
    "ConversationEventStream",
    "ConversationProjectionReader",
    "ConversationProposal",
    "ConversationProposalOutbox",
    "ConversationQuery",
    "ConversationResponse",
    "ConversationStreamReader",
    "ConversationStreamRequest",
    "ConversationUnavailableError",
    "JsonObject",
    "JsonValue",
    "OutboxReceipt",
    "PrincipalScope",
    "StreamEvent",
]
