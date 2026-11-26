"""Pure workflow trigger-event registry contracts shared by Core and Operator."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field

from fdai_service_contracts.workflow_catalog.base import WorkflowCatalogBase


class WorkflowTriggerEventSemantics(StrEnum):
    """What a Workflow-only trigger event means."""

    REQUEST = "request"
    COMMAND = "command"
    OBSERVATION = "observation"


class WorkflowTriggerEventEntry(WorkflowCatalogBase):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+$")]
    semantics: WorkflowTriggerEventSemantics
    description: Annotated[str, Field(min_length=1, max_length=512)]
    owner: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*$")]


class WorkflowTriggerEventRegistry(WorkflowCatalogBase):
    schema_version: str
    events: tuple[WorkflowTriggerEventEntry, ...]

    def model_post_init(self, __context: Any) -> None:
        ids = tuple(item.id for item in self.events)
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow trigger event ids MUST be unique")

    def ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.events)


__all__ = [
    "WorkflowTriggerEventEntry",
    "WorkflowTriggerEventRegistry",
    "WorkflowTriggerEventSemantics",
]
