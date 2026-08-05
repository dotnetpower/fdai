"""Typed lifecycle boundary for one Operator API conversation turn.

Responsibility: validate immutable server-derived turn identity, run an
injected in-process turn processor, and project terminal payloads into typed
results without changing their public wire shape. Authority: none; this module
cannot approve, execute, promote, select provider scope, or receive Thor's
identity. State is request-local and immutable. Dependencies are typed async
callbacks only. Deployment role: shared in-process by JSON and SSE adapters;
there is no network hop or independently deployed service.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias

FrozenJsonValue: TypeAlias = (  # noqa: UP040 - parsed by the system-Python boundary gate
    None
    | bool
    | int
    | float
    | str
    | tuple["FrozenJsonValue", ...]
    | Mapping[str, "FrozenJsonValue"]
)
JsonValue: TypeAlias = (  # noqa: UP040 - parsed by the system-Python boundary gate
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
TurnProcessor: TypeAlias = Callable[  # noqa: UP040 - parsed by the system-Python boundary gate
    ["ConversationTurnInput"], Awaitable[Mapping[str, object]]
]

_MAX_ID_CHARS = 512
_MAX_PROMPT_CHARS = 1_000_000
_MAX_EVIDENCE_REFS = 64
_MAX_EVIDENCE_REF_CHARS = 1024
_MAX_HISTORY_TURNS = 10_000
_MAX_JSON_DEPTH = 64
_VERIFICATION_STATUSES = frozenset({"verified", "consistent", "corrected", "unverified"})


class ConversationTurnTerminalStatus(StrEnum):
    """Closed terminal outcomes represented by the application boundary."""

    COMPLETED = "completed"
    CORRECTED = "corrected"
    UNVERIFIED = "unverified"
    ABSTAINED = "abstained"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConversationTurnInput:
    """Immutable server-derived input that carries no provider or action authority."""

    principal_id: str
    conversation_id: str
    request_id: str
    correlation_id: str
    prompt: str
    response_locale: str | None = None
    target_agent: str | None = None
    evidence_refs: tuple[str, ...] = ()
    history_turn_count: int = 0
    streaming: bool = False

    def __post_init__(self) -> None:
        _require_text("principal_id", self.principal_id, _MAX_ID_CHARS)
        _require_text("conversation_id", self.conversation_id, _MAX_ID_CHARS)
        _require_text("request_id", self.request_id, _MAX_ID_CHARS)
        _require_text("correlation_id", self.correlation_id, _MAX_ID_CHARS)
        _require_prompt(self.prompt)
        if self.response_locale is not None:
            _require_text("response_locale", self.response_locale, 64)
        if self.target_agent is not None:
            _require_text("target_agent", self.target_agent, 64)
        if isinstance(self.evidence_refs, (str, bytes)):
            raise ValueError("evidence_refs MUST be a sequence of strings")
        evidence_refs = tuple(self.evidence_refs)
        if len(evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("evidence_refs exceeds the turn input bound")
        for evidence_ref in evidence_refs:
            if not isinstance(evidence_ref, str):
                raise ValueError("evidence_ref MUST be a string")
            _require_text("evidence_ref", evidence_ref, _MAX_EVIDENCE_REF_CHARS)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        if not 0 <= self.history_turn_count <= _MAX_HISTORY_TURNS:
            raise ValueError("history_turn_count is outside the turn input bound")

    @property
    def assistant_idempotency_key(self) -> str:
        """Return the existing server-owned assistant-turn idempotency key."""
        return f"{self.request_id}:assistant"


@dataclass(frozen=True, slots=True)
class ConversationTurnExecution:
    """One request-local lifecycle token that accepts exactly one terminal result."""

    request: ConversationTurnInput
    _result: ConversationTurnResult | None = field(default=None, init=False, repr=False)

    @property
    def closed(self) -> bool:
        """Return whether this execution already accepted a terminal result."""
        return self._result is not None

    def close(self, result: ConversationTurnResult) -> ConversationTurnResult:
        """Record one terminal result and reject contradictory double closure."""
        if self._result is not None:
            raise RuntimeError("conversation turn execution is already closed")
        if (
            result.conversation_id != self.request.conversation_id
            or result.request_id != self.request.request_id
        ):
            raise ValueError("terminal result identity conflicts with turn execution")
        _validate_wire_identity(self.request, result.wire_payload)
        object.__setattr__(self, "_result", result)
        return result


@dataclass(frozen=True, slots=True)
class ConversationTurnVerification:
    """Typed terminal verification summary retained by every answered turn."""

    status: str
    authority: str | None
    reason_code: str | None
    evidence_refs: tuple[str, ...]
    checks_completed: int
    checks_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, str):
            raise ValueError("terminal verification status MUST be a string")
        if self.status not in _VERIFICATION_STATUSES:
            raise ValueError("terminal verification status is invalid")
        if isinstance(self.evidence_refs, (str, bytes)):
            raise ValueError("terminal verification evidence_refs MUST be a sequence")
        evidence_refs = tuple(self.evidence_refs)
        if len(evidence_refs) > _MAX_EVIDENCE_REFS or not all(
            isinstance(item, str) for item in evidence_refs
        ):
            raise ValueError("terminal verification evidence_refs are invalid")
        for evidence_ref in evidence_refs:
            _require_text(
                "terminal verification evidence_ref",
                evidence_ref,
                _MAX_EVIDENCE_REF_CHARS,
            )
        object.__setattr__(self, "evidence_refs", evidence_refs)
        if self.authority is not None:
            _require_text("terminal verification authority", self.authority, 256)
        if self.reason_code is not None:
            _require_text("terminal verification reason_code", self.reason_code, 256)
        if (
            isinstance(self.checks_completed, bool)
            or isinstance(self.checks_total, bool)
            or self.checks_completed < 0
            or self.checks_total < self.checks_completed
        ):
            raise ValueError("terminal verification check counts are invalid")


@dataclass(frozen=True, slots=True)
class ConversationTurnResult:
    """Immutable typed terminal result with an exact frozen wire snapshot."""

    conversation_id: str
    request_id: str
    terminal_status: ConversationTurnTerminalStatus
    answer: str | None
    verification: ConversationTurnVerification | None
    evidence_refs: tuple[str, ...]
    presentation_artifact: Mapping[str, FrozenJsonValue] | None
    delegation: Mapping[str, FrozenJsonValue] | None
    model: str | None
    source: str | None
    failure_code: str | None
    failure_detail: str | None
    wire_payload: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        _require_text("conversation_id", self.conversation_id, _MAX_ID_CHARS)
        _require_text("request_id", self.request_id, _MAX_ID_CHARS)
        if not isinstance(self.terminal_status, ConversationTurnTerminalStatus):
            raise ValueError("terminal_status MUST be a ConversationTurnTerminalStatus")
        if isinstance(self.evidence_refs, (str, bytes)):
            raise ValueError("result evidence_refs MUST be a sequence")
        evidence_refs = tuple(self.evidence_refs)
        if len(evidence_refs) > _MAX_EVIDENCE_REFS or not all(
            isinstance(item, str) for item in evidence_refs
        ):
            raise ValueError("result evidence_refs MUST contain strings")
        for evidence_ref in evidence_refs:
            _require_text("result evidence_ref", evidence_ref, _MAX_EVIDENCE_REF_CHARS)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        if self.presentation_artifact is not None:
            object.__setattr__(
                self,
                "presentation_artifact",
                _freeze_mapping(self.presentation_artifact),
            )
        if self.delegation is not None:
            object.__setattr__(self, "delegation", _freeze_mapping(self.delegation))
        frozen_payload = _freeze_mapping(self.wire_payload)
        object.__setattr__(self, "wire_payload", frozen_payload)
        failure_status = self.terminal_status in {
            ConversationTurnTerminalStatus.ABSTAINED,
            ConversationTurnTerminalStatus.UNAVAILABLE,
            ConversationTurnTerminalStatus.CANCELLED,
            ConversationTurnTerminalStatus.FAILED,
        }
        if failure_status:
            if self.answer is not None or self.verification is not None:
                raise ValueError("failure result cannot carry an answer or verification")
            if (
                frozen_payload.get("answer") is not None
                or frozen_payload.get("verification") is not None
            ):
                raise ValueError("failure wire payload cannot advertise success")
            if self.failure_code is None or self.failure_detail is None:
                raise ValueError("failure result requires code and detail")
        elif (
            not isinstance(self.answer, str)
            or not self.answer
            or (
                self.verification is not None
                and not isinstance(self.verification, ConversationTurnVerification)
            )
            or self.failure_code is not None
            or self.failure_detail is not None
        ):
            raise ValueError("successful result has inconsistent terminal fields")

    def to_wire_payload(self) -> dict[str, JsonValue]:
        """Return a mutable JSON value identical to the accepted terminal payload."""
        return _thaw_mapping(self.wire_payload)


class ConversationTurnApplicationService:
    """Run and close typed conversation lifecycles without transport authority."""

    def start_turn(self, request: ConversationTurnInput) -> ConversationTurnExecution:
        """Start one validated request-local lifecycle token."""
        return ConversationTurnExecution(request=request)

    async def execute(
        self,
        request: ConversationTurnInput,
        processor: TurnProcessor,
    ) -> ConversationTurnResult:
        """Run a complete in-process turn and return its typed terminal result."""
        execution = self.start_turn(request)
        payload = await processor(request)
        return self.complete_turn(execution, payload)

    def complete_turn(
        self,
        execution: ConversationTurnExecution,
        payload: Mapping[str, object],
        *,
        terminal_status: ConversationTurnTerminalStatus | None = None,
    ) -> ConversationTurnResult:
        """Validate and freeze one existing terminal payload without changing it."""
        result = self.validate_turn_result(
            execution,
            payload,
            terminal_status=terminal_status,
        )
        return execution.close(result)

    def validate_turn_result(
        self,
        execution: ConversationTurnExecution,
        payload: Mapping[str, object],
        *,
        terminal_status: ConversationTurnTerminalStatus | None = None,
    ) -> ConversationTurnResult:
        """Build a typed result without closing its request-local execution token."""
        _validate_wire_identity(execution.request, payload)
        frozen_payload = _freeze_mapping(payload)
        verification = _verification(payload.get("verification"))
        derived_status = _terminal_status(verification)
        if terminal_status is None:
            status = derived_status
        elif terminal_status in {
            ConversationTurnTerminalStatus.COMPLETED,
            ConversationTurnTerminalStatus.CORRECTED,
            ConversationTurnTerminalStatus.UNVERIFIED,
        }:
            if derived_status is not terminal_status:
                raise ValueError("terminal status conflicts with verification")
            status = terminal_status
        else:
            raise ValueError("complete_turn only accepts successful terminal statuses")
        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer:
            raise ValueError("terminal answer MUST be a non-empty string")
        evidence_refs = verification.evidence_refs if verification is not None else ()
        return ConversationTurnResult(
            conversation_id=execution.request.conversation_id,
            request_id=execution.request.request_id,
            terminal_status=status,
            answer=answer,
            verification=verification,
            evidence_refs=evidence_refs,
            presentation_artifact=_optional_frozen_mapping(
                frozen_payload.get("presentation_artifact")
            ),
            delegation=_optional_frozen_mapping(frozen_payload.get("delegation")),
            model=_optional_string(payload.get("model")),
            source=_optional_string(payload.get("source")),
            failure_code=None,
            failure_detail=None,
            wire_payload=frozen_payload,
        )

    def terminate_turn(
        self,
        execution: ConversationTurnExecution,
        *,
        terminal_status: ConversationTurnTerminalStatus,
        code: str,
        detail: str,
        wire_payload: Mapping[str, object],
    ) -> ConversationTurnResult:
        """Close an explicit abstained, unavailable, cancelled, or failed turn."""
        if terminal_status not in {
            ConversationTurnTerminalStatus.ABSTAINED,
            ConversationTurnTerminalStatus.UNAVAILABLE,
            ConversationTurnTerminalStatus.CANCELLED,
            ConversationTurnTerminalStatus.FAILED,
        }:
            raise ValueError("terminal failure status is not supported")
        _require_text("failure code", code, 128)
        _require_text("failure detail", detail, 1024)
        _validate_wire_identity(execution.request, wire_payload)
        result = ConversationTurnResult(
            conversation_id=execution.request.conversation_id,
            request_id=execution.request.request_id,
            terminal_status=terminal_status,
            answer=None,
            verification=None,
            evidence_refs=(),
            presentation_artifact=None,
            delegation=None,
            model=None,
            source=None,
            failure_code=code,
            failure_detail=detail,
            wire_payload=_freeze_mapping(wire_payload),
        )
        return execution.close(result)


def _verification(value: object) -> ConversationTurnVerification | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("terminal verification MUST be an object")
    status = _required_mapping_text(value, "status")
    if status not in _VERIFICATION_STATUSES:
        raise ValueError("terminal verification status is invalid")
    raw_refs = value.get("evidence_refs", ())
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)):
        raise ValueError("terminal verification evidence_refs MUST be a sequence")
    if len(raw_refs) > _MAX_EVIDENCE_REFS:
        raise ValueError("terminal verification evidence_refs exceeds the bound")
    if not all(isinstance(item, str) for item in raw_refs):
        raise ValueError("terminal verification evidence_refs MUST contain strings")
    evidence_refs = tuple(raw_refs)
    for evidence_ref in evidence_refs:
        _require_text("verification evidence_ref", evidence_ref, _MAX_EVIDENCE_REF_CHARS)
    checks_completed = value.get("checks_completed", 0)
    checks_total = value.get("checks_total", 0)
    if (
        not isinstance(checks_completed, int)
        or isinstance(checks_completed, bool)
        or not isinstance(checks_total, int)
        or isinstance(checks_total, bool)
        or checks_completed < 0
        or checks_total < checks_completed
    ):
        raise ValueError("terminal verification check counts are invalid")
    return ConversationTurnVerification(
        status=status,
        authority=_optional_string(value.get("authority")),
        reason_code=_optional_string(value.get("reason_code")),
        evidence_refs=evidence_refs,
        checks_completed=checks_completed,
        checks_total=checks_total,
    )


def _terminal_status(
    verification: ConversationTurnVerification | None,
) -> ConversationTurnTerminalStatus:
    if verification is None:
        return ConversationTurnTerminalStatus.UNVERIFIED
    if verification.status == "corrected":
        return ConversationTurnTerminalStatus.CORRECTED
    if verification.status == "verified":
        return ConversationTurnTerminalStatus.COMPLETED
    return ConversationTurnTerminalStatus.UNVERIFIED


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, FrozenJsonValue]:
    return _freeze_mapping_at_depth(value, active=set(), depth=0)


def _freeze_mapping_at_depth(
    value: Mapping[str, object],
    *,
    active: set[int],
    depth: int,
) -> Mapping[str, FrozenJsonValue]:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("terminal payload exceeds the JSON depth bound")
    identity = id(value)
    if identity in active:
        raise ValueError("terminal payload contains a cyclic value")
    active.add(identity)
    frozen: dict[str, FrozenJsonValue] = {}
    try:
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("terminal payload keys MUST be strings")
            frozen[key] = _freeze(item, active=active, depth=depth + 1)
        return MappingProxyType(frozen)
    finally:
        active.remove(identity)


def _freeze(value: object, *, active: set[int], depth: int) -> FrozenJsonValue:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("terminal payload exceeds the JSON depth bound")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("terminal payload numbers MUST be finite")
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping_at_depth(value, active=active, depth=depth)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        identity = id(value)
        if identity in active:
            raise ValueError("terminal payload contains a cyclic value")
        active.add(identity)
        try:
            return tuple(_freeze(item, active=active, depth=depth + 1) for item in value)
        finally:
            active.remove(identity)
    raise ValueError(f"terminal payload contains unsupported value {type(value).__name__}")


def _thaw_mapping(value: Mapping[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    return {key: _thaw(item) for key, item in value.items()}


def _thaw(value: FrozenJsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _optional_frozen_mapping(
    value: FrozenJsonValue | None,
) -> Mapping[str, FrozenJsonValue] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("terminal metadata MUST be an object or null")
    return value


def _required_mapping_text(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"terminal verification {key} MUST be a string")
    _require_text(f"terminal verification {key}", item, 256)
    return item


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("terminal metadata string has invalid type")
    return value


def _validate_wire_identity(
    request: ConversationTurnInput,
    payload: Mapping[str, object],
) -> None:
    expected = {
        "request_id": request.request_id,
        "session_id": request.conversation_id,
        "conversation_id": request.conversation_id,
    }
    for key, expected_value in expected.items():
        value = payload.get(key)
        if value is not None and value != expected_value:
            raise ValueError(f"terminal payload {key} conflicts with turn identity")


def _require_text(name: str, value: str, maximum: int) -> None:
    if not value or len(value) > maximum or any(character in value for character in "\x00\r\n"):
        raise ValueError(f"{name} MUST be non-empty, bounded, single-line text")


def _require_prompt(value: str) -> None:
    if not value or len(value) > _MAX_PROMPT_CHARS or "\x00" in value:
        raise ValueError("prompt MUST be non-empty, bounded text")
