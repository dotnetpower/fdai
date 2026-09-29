"""Strict catalog for Workflow signal triggers that are not T0 SignalTypes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "workflow_trigger_events.schema.json"


class WorkflowTriggerEventSemantics(StrEnum):
    REQUEST = "request"
    COMMAND = "command"


class WorkflowTriggerEventEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+$")]
    semantics: WorkflowTriggerEventSemantics
    description: Annotated[str, Field(min_length=1, max_length=512)]
    owner: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*$")]


class WorkflowTriggerEventRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    events: tuple[WorkflowTriggerEventEntry, ...]

    def model_post_init(self, __context: Any) -> None:
        ids = tuple(item.id for item in self.events)
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow trigger event ids MUST be unique")

    def ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.events)


class WorkflowTriggerEventRegistryError(ValueError):
    """Raised when the Workflow trigger event catalog is malformed."""


def load_workflow_trigger_event_registry_from_mapping(
    raw: Mapping[str, Any],
) -> WorkflowTriggerEventRegistry:
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(raw)), key=lambda e: list(e.path))
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise WorkflowTriggerEventRegistryError(
            f"workflow-trigger-event registry validation failed: {preview}"
        )
    try:
        return WorkflowTriggerEventRegistry.model_validate(raw)
    except ValidationError as exc:
        raise WorkflowTriggerEventRegistryError(
            f"workflow-trigger-event registry validation failed: {exc}"
        ) from exc


__all__ = [
    "WorkflowTriggerEventEntry",
    "WorkflowTriggerEventRegistry",
    "WorkflowTriggerEventRegistryError",
    "WorkflowTriggerEventSemantics",
    "load_workflow_trigger_event_registry_from_mapping",
]
