"""Versioned ownership-only declarations; no role, membership, or execution authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExactRef = Annotated[str, Field(strict=True, min_length=1, max_length=256, pattern=r"^[!-~]+$")]
AgentName = Literal[
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Vidar",
    "Var",
    "Bragi",
    "Saga",
    "Mimir",
    "Muninn",
    "Norns",
    "Njord",
    "Freyr",
    "Loki",
]


class ScopedDutySubject(BaseModel):
    """An exact normalized person, group, or configured rotation, never a search query."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["user", "group", "schedule"]
    ref: ExactRef

    @field_validator("ref")
    @classmethod
    def normalized_reference(cls, value: str) -> str:
        """Require callers to provide canonical identity rather than silently rewriting it."""
        if value != value.casefold():
            raise ValueError("scoped subject reference MUST already be normalized")
        return value


class ScopedDutyDeclaration(BaseModel):
    """One finite duty interval; a schedule requires a separately resolved static person."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    subject: ScopedDutySubject
    agent_name: AgentName
    scope_ref: ExactRef
    duty: Literal["primary", "backup", "escalation"]
    effective_from: datetime
    effective_until: datetime
    fallback: ScopedDutySubject | None

    @field_validator("effective_from", "effective_until", mode="before")
    @classmethod
    def explicit_time(cls, value: object) -> object:
        """Numeric epochs and implicit local time are not valid declaration timestamps."""
        if not isinstance(value, str | datetime):
            raise ValueError("scoped duty time MUST be explicit offset-aware timestamp text")
        return value

    @field_validator("effective_from", "effective_until")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        """Normalize an explicitly offset-aware instant without changing its meaning."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scoped duty time MUST have a defined offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_declaration(self) -> ScopedDutyDeclaration:
        """Reject empty intervals and invented group or recursive schedule fallbacks."""
        if self.effective_from >= self.effective_until:
            raise ValueError("scoped duty interval MUST be nonempty and half-open")
        if self.subject.kind == "schedule":
            if (
                self.fallback is None
                or self.fallback.kind != "user"
                or self.fallback.ref == self.subject.ref
            ):
                raise ValueError("schedule MUST declare one distinct static person fallback")
        elif self.fallback is not None:
            raise ValueError("only a schedule may declare fallback")
        return self


class ScopedDutyRequest(BaseModel):
    """Immutable reviewed intent, not an aggregate IAM grant or a v2 map overlay."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_revision: ExactRef
    bindings: Annotated[tuple[ScopedDutyDeclaration, ...], Field(min_length=1, max_length=30)]
    supersedes_case_id: Annotated[str, Field(pattern=r"^[a-f0-9-]{36}$")] | None = None

    @model_validator(mode="after")
    def nonoverlapping_declarations(self) -> ScopedDutyRequest:
        """Same declared subject/agent/scope cannot occupy overlapping duty intervals."""
        for index, binding in enumerate(self.bindings):
            for previous in self.bindings[:index]:
                if (
                    (binding.subject, binding.agent_name, binding.scope_ref)
                    == (previous.subject, previous.agent_name, previous.scope_ref)
                    and binding.effective_from < previous.effective_until
                    and previous.effective_from < binding.effective_until
                ):
                    raise ValueError("same scoped subject MUST NOT have overlapping duty windows")
        return self


__all__ = [
    "AgentName",
    "ExactRef",
    "ScopedDutyDeclaration",
    "ScopedDutyRequest",
    "ScopedDutySubject",
]
