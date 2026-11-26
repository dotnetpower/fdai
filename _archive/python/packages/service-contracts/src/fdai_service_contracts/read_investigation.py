"""Authority-free read-investigation requests shared by Operator and Core."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest

READ_INVESTIGATION_REQUEST_TOPIC = "operator.read-investigation.requests"
READ_INVESTIGATION_CONSUMER_GROUP = "core-read-investigation-v1"
READ_INVESTIGATION_COMPLETION_TOPIC = "core.read-investigation.completions"
READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP = "operator-read-investigation-completion-v1"


class ReadInvestigationContract(BaseModel):
    """Provide immutable fail-closed validation for the cross-service request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(ord(character) < 32 for character in value):
            raise ValueError("read investigation text MUST NOT contain control characters")
        return value


class ReadInvestigationOrigin(ReadInvestigationContract):
    """Identify the bounded conversation or API surface that owns completion."""

    conversation_id: Annotated[str, Field(min_length=1, max_length=256)]
    channel_kind: Annotated[str, Field(min_length=1, max_length=64)]
    channel_id: Annotated[str, Field(min_length=1, max_length=256)]
    thread_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    message_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class ReadInvestigationIntent(StrEnum):
    """Registered read meanings accepted by the Core planner."""

    RESOURCE_STATE = "resource_state"
    CHANGE_ATTRIBUTION = "change_attribution"
    RESOURCE_CHANGE_HISTORY = "resource_change_history"
    PLATFORM_HEALTH = "platform_health"
    GUEST_SHUTDOWN = "guest_shutdown"
    NETWORK_SECURITY = "network_security"
    NETWORK_PEERING = "network_peering"


class ReadInvestigationSelector(ReadInvestigationContract):
    """Carry only source-grounded target hints; Core supplies provider scope."""

    name: Annotated[str, Field(min_length=1, max_length=512)]
    resource_type: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    resource_group: Annotated[str, Field(min_length=1, max_length=512)] | None = None


class ReadInvestigationProposalBody(ReadInvestigationContract):
    """Validate the public typed request before durable Operator acceptance."""

    prompt: Annotated[str, Field(min_length=1, max_length=4_000)]
    intent: ReadInvestigationIntent
    resource_name: Annotated[str, Field(min_length=1, max_length=512)]
    resource_type: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    resource_group: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    explicit_deep: Annotated[bool, Field(strict=True)] = False


class ReadInvestigationTaskBudget(ReadInvestigationContract):
    """Carry the server-owned detached-task ceilings across the process boundary."""

    max_wall_seconds: Annotated[int, Field(ge=1, le=3_600)] = 300
    max_tokens: Annotated[int, Field(ge=1, le=32_768)] = 4_096
    max_cost_microusd: Annotated[int, Field(ge=0, le=10_000_000)] = 500_000
    max_tool_calls: Annotated[int, Field(ge=0, le=100)] = 5
    max_progress_events: Annotated[int, Field(ge=1, le=256)] = 32


class ReadInvestigationRequest(ReadInvestigationContract):
    """Request one bounded read without granting provider or execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    owner_principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=256)]
    prompt: Annotated[str, Field(min_length=1, max_length=4_000)]
    intent: ReadInvestigationIntent
    selector: ReadInvestigationSelector
    origin: ReadInvestigationOrigin
    budget: ReadInvestigationTaskBudget = ReadInvestigationTaskBudget()
    explicit_deep: Annotated[bool, Field(strict=True)] = False
    requested_at: datetime
    request_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    accountable_agent: Literal["Heimdall"] = "Heimdall"
    capability_profile_id: Literal["background.read-only"] = "background.read-only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_identity(self) -> ReadInvestigationRequest:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("read investigation requested_at MUST be timezone-aware")
        if self.request_digest != read_investigation_request_digest(self):
            raise ValueError("read investigation request digest does not match its content")
        return self


class ReadInvestigationCancellation(ReadInvestigationContract):
    """Cancel one owner-scoped background investigation without execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    command: Literal["cancel"] = "cancel"
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    owner_principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    task_id: Annotated[str, Field(min_length=1, max_length=256)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    requested_at: datetime
    admin_override: Annotated[bool, Field(strict=True)] = False
    request_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_identity(self) -> ReadInvestigationCancellation:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("read investigation cancellation requested_at MUST be timezone-aware")
        material = self.model_dump(mode="json", exclude={"request_digest"})
        if self.request_digest != canonical_digest(material):
            raise ValueError("read investigation cancellation digest does not match its content")
        return self


class ReadInvestigationCompletionUsage(ReadInvestigationContract):
    """Carry bounded terminal usage without provider billing inference."""

    tokens: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    cost_microusd: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    tool_calls: Annotated[int, Field(ge=0, le=100)] = 0


class ReadInvestigationCompletion(ReadInvestigationContract):
    """Transfer one immutable terminal result to the Operator-owned delivery path."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    completion_id: Annotated[str, Field(pattern=r"^read-completion-[a-f0-9]{32}$")]
    task_id: Annotated[str, Field(min_length=1, max_length=256)]
    attempt_id: Annotated[str, Field(min_length=1, max_length=256)]
    attempt_number: Annotated[int, Field(ge=1, le=100)]
    owner_principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=256)]
    origin: ReadInvestigationOrigin
    status: Literal["succeeded", "failed", "cancelled", "timed_out", "unknown"]
    terminal_reason: Annotated[str, Field(min_length=1, max_length=256)]
    summary: Annotated[str, Field(max_length=2_000)] | None = None
    evidence_refs: Annotated[tuple[str, ...], Field(max_length=16)] = ()
    usage: ReadInvestigationCompletionUsage = ReadInvestigationCompletionUsage()
    started_at: datetime
    finished_at: datetime
    completed_at: datetime
    retention_until: datetime
    trusted: Literal[False] = False
    execution_authority: Literal[False] = False
    completion_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("completion evidence_refs MUST be unique")
        if any(
            not item or len(item) > 512 or any(ord(character) < 32 for character in item)
            for item in value
        ):
            raise ValueError("completion evidence_refs MUST be bounded identifiers")
        return value

    @model_validator(mode="after")
    def _validate_completion(self) -> ReadInvestigationCompletion:
        timestamps = (
            self.started_at,
            self.finished_at,
            self.completed_at,
            self.retention_until,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
            raise ValueError("completion timestamps MUST be timezone-aware")
        if not self.started_at <= self.finished_at <= self.completed_at <= self.retention_until:
            raise ValueError("completion timestamps MUST be ordered")
        if self.completion_id != read_investigation_completion_id(
            self.task_id,
            self.attempt_id,
            self.attempt_number,
        ):
            raise ValueError("read investigation completion id does not match its content")
        if self.completion_digest != read_investigation_completion_digest(self):
            raise ValueError("read investigation completion digest does not match its content")
        return self


def read_investigation_request_digest(request: ReadInvestigationRequest) -> str:
    """Return the replay-stable digest excluding only the digest field itself."""

    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


def read_investigation_task_id(owner_principal_id: str, idempotency_key: str) -> str:
    """Return the stable lifecycle partition and background-task identity."""

    digest = hashlib.sha256(
        f"{owner_principal_id}\x00{idempotency_key}".encode("utf-8")
    ).hexdigest()
    return f"background-{digest[:32]}"


def read_investigation_completion_id(
    task_id: str,
    attempt_id: str,
    attempt_number: int,
) -> str:
    """Return the stable inbox identity for one terminal attempt."""

    digest = hashlib.sha256(
        f"{task_id}\x00{attempt_id}\x00{attempt_number}".encode("utf-8")
    ).hexdigest()
    return f"read-completion-{digest[:32]}"


def read_investigation_completion_digest(completion: ReadInvestigationCompletion) -> str:
    """Return the replay-stable digest excluding only the digest field."""

    return canonical_digest(completion.model_dump(mode="json", exclude={"completion_digest"}))


def build_read_investigation_request(
    *,
    request_id: str,
    owner_principal_id: str,
    idempotency_key: str,
    correlation_id: str,
    prompt: str,
    intent: ReadInvestigationIntent | str,
    selector: ReadInvestigationSelector,
    origin: ReadInvestigationOrigin,
    requested_at: datetime,
    budget: ReadInvestigationTaskBudget | None = None,
    explicit_deep: bool = False,
) -> ReadInvestigationRequest:
    """Build one request with canonical defaults and a matching content digest."""

    selected_budget = budget or ReadInvestigationTaskBudget()
    selected_intent = ReadInvestigationIntent(intent)
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "owner_principal_id": owner_principal_id,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
        "prompt": prompt,
        "intent": selected_intent.value,
        "selector": selector.model_dump(mode="json"),
        "origin": origin.model_dump(mode="json"),
        "budget": selected_budget.model_dump(mode="json"),
        "explicit_deep": explicit_deep,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "accountable_agent": "Heimdall",
        "capability_profile_id": "background.read-only",
        "execution_authority": False,
    }
    return ReadInvestigationRequest.model_validate(
        {**material, "request_digest": canonical_digest(material)}
    )


def build_read_investigation_cancellation(
    *,
    request_id: str,
    owner_principal_id: str,
    task_id: str,
    idempotency_key: str,
    requested_at: datetime,
    admin_override: bool,
) -> ReadInvestigationCancellation:
    """Build one cancellation with a matching content digest."""

    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "command": "cancel",
        "request_id": request_id,
        "owner_principal_id": owner_principal_id,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        "admin_override": admin_override,
        "execution_authority": False,
    }
    return ReadInvestigationCancellation.model_validate(
        {**material, "request_digest": canonical_digest(material)}
    )


def build_read_investigation_completion(
    *,
    task_id: str,
    attempt_id: str,
    attempt_number: int,
    owner_principal_id: str,
    request_idempotency_key: str,
    correlation_id: str,
    origin: ReadInvestigationOrigin,
    status: Literal["succeeded", "failed", "cancelled", "timed_out", "unknown"],
    terminal_reason: str,
    summary: str | None,
    evidence_refs: tuple[str, ...],
    usage: ReadInvestigationCompletionUsage,
    started_at: datetime,
    finished_at: datetime,
    completed_at: datetime,
    retention_until: datetime,
) -> ReadInvestigationCompletion:
    """Build one completion with deterministic identity and content digest."""

    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "completion_id": read_investigation_completion_id(
            task_id,
            attempt_id,
            attempt_number,
        ),
        "task_id": task_id,
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "owner_principal_id": owner_principal_id,
        "request_idempotency_key": request_idempotency_key,
        "correlation_id": correlation_id,
        "origin": origin.model_dump(mode="json"),
        "status": status,
        "terminal_reason": terminal_reason,
        "summary": summary,
        "evidence_refs": list(evidence_refs),
        "usage": usage.model_dump(mode="json"),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "retention_until": retention_until.isoformat().replace("+00:00", "Z"),
        "trusted": False,
        "execution_authority": False,
    }
    return ReadInvestigationCompletion.model_validate(
        {**material, "completion_digest": canonical_digest(material)}
    )


__all__ = [
    "READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP",
    "READ_INVESTIGATION_COMPLETION_TOPIC",
    "READ_INVESTIGATION_CONSUMER_GROUP",
    "READ_INVESTIGATION_REQUEST_TOPIC",
    "ReadInvestigationCompletion",
    "ReadInvestigationCompletionUsage",
    "ReadInvestigationOrigin",
    "ReadInvestigationIntent",
    "ReadInvestigationCancellation",
    "ReadInvestigationProposalBody",
    "ReadInvestigationRequest",
    "ReadInvestigationSelector",
    "ReadInvestigationTaskBudget",
    "build_read_investigation_request",
    "build_read_investigation_cancellation",
    "build_read_investigation_completion",
    "read_investigation_completion_digest",
    "read_investigation_completion_id",
    "read_investigation_request_digest",
    "read_investigation_task_id",
]
