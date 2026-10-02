"""Strict catalog loader for Workflow trigger events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

from fdai_service_contracts.workflow_catalog import (
    WorkflowTriggerEventEntry,
    WorkflowTriggerEventRegistry,
    WorkflowTriggerEventSemantics,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "workflow_trigger_events.schema.json"


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
