"""Workflow validation-context projection contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from fdai_service_contracts.workflow_catalog.base import WorkflowCatalogBase
from fdai_service_contracts.workflow_catalog.signal_type import SignalTypeRegistry
from fdai_service_contracts.workflow_catalog.workflow_trigger_event import (
    WorkflowTriggerEventRegistry,
)

WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY = (
    "operator-projection:workflow:workflow.validation-context"
)
WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION = "1.0.0"


class WorkflowValidationContext(WorkflowCatalogBase):
    """Revision-fenced cross-reference set used by Operator draft validation."""

    schema_version: str = WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION
    action_type_names: tuple[Annotated[str, Field(min_length=1)], ...]
    rule_ids: tuple[Annotated[str, Field(min_length=1)], ...]
    signal_types: SignalTypeRegistry
    workflow_trigger_events: WorkflowTriggerEventRegistry
    catalog_revision: Annotated[str, Field(min_length=1)]
    catalog_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def _canonical_sets(self) -> WorkflowValidationContext:
        if tuple(sorted(self.action_type_names)) != self.action_type_names:
            raise ValueError("action_type_names MUST be sorted")
        if len(set(self.action_type_names)) != len(self.action_type_names):
            raise ValueError("action_type_names MUST be unique")
        if tuple(sorted(self.rule_ids)) != self.rule_ids:
            raise ValueError("rule_ids MUST be sorted")
        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("rule_ids MUST be unique")
        return self


__all__ = [
    "WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY",
    "WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION",
    "WorkflowValidationContext",
]
