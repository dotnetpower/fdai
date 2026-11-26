"""Workflow definition metadata and principal-scoped binding contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


class WorkflowOrigin(StrEnum):
    UPSTREAM = "upstream"
    TENANT = "tenant"
    USER = "user"


class WorkflowVisibility(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    PRIVATE = "private"


class WorkflowLifecycle(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    SHADOW = "shadow"
    PUBLISHED = "published"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class WorkflowBindingTrigger(StrEnum):
    DECK_OPEN = "deck_open"
    SCHEDULE = "schedule"
    SIGNAL = "signal"


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionRecord:
    definition_id: str
    workflow_name: str
    workflow_version: str
    schema_version: str
    definition_hash: str
    action_catalog_digest: str
    resolved_action_versions: Mapping[str, str]
    workflow_document: Mapping[str, object]
    origin: WorkflowOrigin
    visibility: WorkflowVisibility
    lifecycle: WorkflowLifecycle
    created_at: datetime
    owner_ref: str | None = None
    derived_from: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("definition_id", self.definition_id),
            ("workflow_name", self.workflow_name),
            ("workflow_version", self.workflow_version),
            ("schema_version", self.schema_version),
            ("definition_hash", self.definition_hash),
            ("action_catalog_digest", self.action_catalog_digest),
        ):
            if not value.strip():
                raise ValueError(f"WorkflowDefinitionRecord.{name} MUST be non-empty")
        if self.created_at.tzinfo is None:
            raise ValueError("WorkflowDefinitionRecord.created_at MUST be timezone-aware")
        if self.origin is WorkflowOrigin.USER and self.owner_ref is None:
            raise ValueError("user workflow definition requires owner_ref")
        if self.visibility is WorkflowVisibility.PRIVATE and self.owner_ref is None:
            raise ValueError("private workflow definition requires owner_ref")
        if not self.workflow_document:
            raise ValueError("WorkflowDefinitionRecord.workflow_document MUST be non-empty")


@dataclass(frozen=True, slots=True)
class WorkflowBindingRecord:
    binding_id: str
    principal_id: str
    definition_id: str
    trigger: WorkflowBindingTrigger
    enabled: bool
    created_at: datetime
    updated_at: datetime
    revision: int = 0
    scope_ref: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    signal_type: str | None = None
    parameters: Mapping[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("binding_id", self.binding_id),
            ("principal_id", self.principal_id),
            ("definition_id", self.definition_id),
        ):
            if not value.strip():
                raise ValueError(f"WorkflowBindingRecord.{name} MUST be non-empty")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("WorkflowBindingRecord timestamps MUST be timezone-aware")
        if self.revision < 0:
            raise ValueError("WorkflowBindingRecord.revision MUST be >= 0")
        if self.trigger is WorkflowBindingTrigger.SCHEDULE:
            if self.cron_expression is None or self.timezone is None:
                raise ValueError("schedule binding requires cron_expression and timezone")
            if len(self.cron_expression.split()) != 5 or not croniter.is_valid(
                self.cron_expression, strict=True
            ):
                raise ValueError("schedule binding requires strict 5-field cron")
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"unknown IANA timezone {self.timezone!r}") from exc
        elif self.cron_expression is not None or self.timezone is not None:
            raise ValueError("non-schedule binding MUST NOT declare cron_expression or timezone")
        if self.trigger is WorkflowBindingTrigger.SIGNAL:
            if self.signal_type is None:
                raise ValueError("signal binding requires signal_type")
        elif self.signal_type is not None:
            raise ValueError("non-signal binding MUST NOT declare signal_type")


class WorkflowDefinitionConflictError(RuntimeError):
    """A workflow definition or binding write conflicts with persisted state."""


@runtime_checkable
class WorkflowDefinitionStore(Protocol):
    async def put(self, record: WorkflowDefinitionRecord) -> WorkflowDefinitionRecord: ...

    async def get(self, *, definition_id: str) -> WorkflowDefinitionRecord | None: ...

    async def list_visible(
        self, *, principal_id: str, team_refs: Sequence[str] = ()
    ) -> Sequence[WorkflowDefinitionRecord]: ...


@runtime_checkable
class WorkflowBindingStore(Protocol):
    async def create(self, record: WorkflowBindingRecord) -> WorkflowBindingRecord: ...

    async def list_for_principal(self, *, principal_id: str) -> Sequence[WorkflowBindingRecord]: ...

    async def put(
        self, record: WorkflowBindingRecord, *, expected_revision: int
    ) -> WorkflowBindingRecord: ...

    async def delete(self, *, principal_id: str, binding_id: str) -> bool: ...


__all__ = [
    "WorkflowBindingRecord",
    "WorkflowBindingStore",
    "WorkflowBindingTrigger",
    "WorkflowDefinitionConflictError",
    "WorkflowDefinitionRecord",
    "WorkflowDefinitionStore",
    "WorkflowLifecycle",
    "WorkflowOrigin",
    "WorkflowVisibility",
]
