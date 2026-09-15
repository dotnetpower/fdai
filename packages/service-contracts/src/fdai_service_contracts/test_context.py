"""Cross-service, no-execution-authority commands for reviewed test context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.ontology_query import content_digest

Text = Annotated[str, Field(min_length=1, max_length=512)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
TEST_CONTEXT_RESULT_TOPIC = "core.test-context.projections"


class TestContextWindow(BaseModel):
    """Complete expected range and explicit aware interval, without approval semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    expected_min: Annotated[float, Field(strict=True)]
    expected_max: Annotated[float, Field(strict=True)]
    effective_from: datetime
    effective_to: datetime

    @model_validator(mode="after")
    def _ordered(self) -> TestContextWindow:
        if (
            self.expected_min > self.expected_max
            or self.effective_from.utcoffset() is None
            or self.effective_to.utcoffset() is None
            or self.effective_from >= self.effective_to
        ):
            raise ValueError("test context proposal interval and range are invalid")
        return self


class TestContextDraft(BaseModel):
    """Source-grounded chat draft requiring scope selection and independent governance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target_ref: Text
    signal_code: Text
    window: TestContextWindow
    source_ref: Text
    semantic_receipt: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False


class TestContextRequest(BaseModel):
    """Typed proposal, independent review, or revocation; never interpreted from keywords."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    operation: Literal["propose", "review", "revoke"]
    context_id: Text
    access_scope_digest: Digest
    target_ref: Text
    signal_code: Text
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    policy_revision: Text
    source_ref: Text
    semantic_receipt: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    expected_min: Annotated[float, Field(strict=True)] | None = None
    expected_max: Annotated[float, Field(strict=True)] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    @model_validator(mode="after")
    def _envelope(self) -> TestContextRequest:
        fields = (self.expected_min, self.expected_max, self.effective_from, self.effective_to)
        if self.operation == "propose":
            if self.expected_revision != 0 or any(value is None for value in fields):
                raise ValueError("test context proposal requires its complete initial envelope")
            assert self.expected_min is not None and self.expected_max is not None
            assert self.effective_from is not None and self.effective_to is not None
            if (
                self.expected_min > self.expected_max
                or self.effective_from.utcoffset() is None
                or self.effective_to.utcoffset() is None
                or self.effective_from >= self.effective_to
            ):
                raise ValueError("test context proposal interval and range are invalid")
        elif self.expected_revision < 1 or any(value is not None for value in fields):
            raise ValueError("test context review cannot replace the proposed envelope")
        return self


class TestContextCommand(BaseModel):
    """Operator-authenticated command, still requiring Core admission before any state change."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    request: TestContextRequest
    actor_id: Text
    actor_roles: tuple[Literal["Contributor", "Approver", "Owner"], ...]
    idempotency_key: Text
    requested_at: datetime
    execution_authority: Literal[False] = False

    @field_validator("actor_roles")
    @classmethod
    def _canonical_roles(
        cls, values: tuple[Literal["Contributor", "Approver", "Owner"], ...]
    ) -> tuple[Literal["Contributor", "Approver", "Owner"], ...]:
        if len(set(values)) != len(values):
            raise ValueError("test context command roles must be unique")
        return tuple(sorted(values))

    @field_validator("requested_at")
    @classmethod
    def _canonical_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("test context request time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _identity(self) -> TestContextCommand:
        if (
            self.requested_at.utcoffset() is None
            or not self.actor_roles
            or len(self.actor_roles) > 3
        ):
            raise ValueError("test context command requires current authenticated role evidence")
        if self.request.operation != "propose" and not set(self.actor_roles) & {
            "Approver",
            "Owner",
        }:
            raise ValueError("test context review requires an Approver or Owner")
        return self


class TestContextApplication(BaseModel):
    """Exact command-to-policy transition result; historical application is not current authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    command_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    actor_id: Text
    request_key: Text
    context_id: Text
    access_scope_digest: Digest
    target_ref: Text
    policy_revision: Text
    revision: Annotated[int, Field(strict=True, ge=1)]
    state: Literal["proposed", "reviewed", "revoked"]
    context_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    execution_authority: Literal[False] = False

    def matches(self, command: TestContextCommand) -> bool:
        """Bind a result to the authenticated original request before persisting status."""
        request = command.request
        return (
            self.command_digest == content_digest(command.model_dump(mode="json"))
            and self.actor_id == command.actor_id
            and self.request_key == command.idempotency_key
            and self.context_id == request.context_id
            and self.access_scope_digest == request.access_scope_digest
            and self.target_ref == request.target_ref
            and self.policy_revision == request.policy_revision
            and self.revision == request.expected_revision + 1
            and self.state
            == {"propose": "proposed", "review": "reviewed", "revoke": "revoked"}[request.operation]
        )
