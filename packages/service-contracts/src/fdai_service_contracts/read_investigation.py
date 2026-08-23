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


def read_investigation_request_digest(request: ReadInvestigationRequest) -> str:
    """Return the replay-stable digest excluding only the digest field itself."""

    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


def read_investigation_task_id(owner_principal_id: str, idempotency_key: str) -> str:
    """Return the stable lifecycle partition and background-task identity."""

    digest = hashlib.sha256(
        f"{owner_principal_id}\x00{idempotency_key}".encode("utf-8")
    ).hexdigest()
    return f"background-{digest[:32]}"


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


__all__ = [
    "READ_INVESTIGATION_CONSUMER_GROUP",
    "READ_INVESTIGATION_REQUEST_TOPIC",
    "ReadInvestigationOrigin",
    "ReadInvestigationIntent",
    "ReadInvestigationCancellation",
    "ReadInvestigationProposalBody",
    "ReadInvestigationRequest",
    "ReadInvestigationSelector",
    "ReadInvestigationTaskBudget",
    "build_read_investigation_request",
    "build_read_investigation_cancellation",
    "read_investigation_request_digest",
    "read_investigation_task_id",
]
