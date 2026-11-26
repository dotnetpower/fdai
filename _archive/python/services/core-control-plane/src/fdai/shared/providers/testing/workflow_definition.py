"""In-memory workflow definition and binding stores."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from fdai.shared.providers.workflow_definition import (
    WorkflowBindingRecord,
    WorkflowDefinitionConflictError,
    WorkflowDefinitionRecord,
    WorkflowVisibility,
)


class InMemoryWorkflowDefinitionStore:
    def __init__(self, records: tuple[WorkflowDefinitionRecord, ...] = ()) -> None:
        self._records: dict[str, WorkflowDefinitionRecord] = {
            record.definition_id: record for record in records
        }

    async def put(self, record: WorkflowDefinitionRecord) -> WorkflowDefinitionRecord:
        existing = self._records.get(record.definition_id)
        if existing is not None and existing != record:
            raise WorkflowDefinitionConflictError(
                f"definition {record.definition_id!r} is immutable"
            )
        self._records[record.definition_id] = record
        return record

    async def get(self, *, definition_id: str) -> WorkflowDefinitionRecord | None:
        return self._records.get(definition_id)

    async def list_visible(
        self, *, principal_id: str, team_refs: Sequence[str] = ()
    ) -> tuple[WorkflowDefinitionRecord, ...]:
        visible = []
        for record in self._records.values():
            if record.visibility is WorkflowVisibility.GLOBAL:
                visible.append(record)
            elif record.visibility is WorkflowVisibility.PRIVATE:
                if record.owner_ref == principal_id:
                    visible.append(record)
            elif record.owner_ref in team_refs:
                visible.append(record)
        return tuple(sorted(visible, key=lambda item: (item.workflow_name, item.workflow_version)))


class InMemoryWorkflowBindingStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], WorkflowBindingRecord] = {}

    async def create(self, record: WorkflowBindingRecord) -> WorkflowBindingRecord:
        key = (record.principal_id, record.binding_id)
        if key in self._records:
            raise WorkflowDefinitionConflictError(f"binding {record.binding_id!r} already exists")
        stored = replace(record, revision=1)
        self._records[key] = stored
        return stored

    async def list_for_principal(self, *, principal_id: str) -> tuple[WorkflowBindingRecord, ...]:
        found = [record for (owner, _), record in self._records.items() if owner == principal_id]
        return tuple(sorted(found, key=lambda item: item.binding_id))

    async def put(
        self, record: WorkflowBindingRecord, *, expected_revision: int
    ) -> WorkflowBindingRecord:
        key = (record.principal_id, record.binding_id)
        existing = self._records.get(key)
        if existing is None:
            raise LookupError(f"binding {record.binding_id!r} not found")
        if existing.revision != expected_revision:
            raise WorkflowDefinitionConflictError(
                f"binding revision mismatch: expected {expected_revision}, "
                f"current {existing.revision}"
            )
        stored = replace(record, revision=existing.revision + 1)
        self._records[key] = stored
        return stored

    async def delete(self, *, principal_id: str, binding_id: str) -> bool:
        return self._records.pop((principal_id, binding_id), None) is not None


__all__ = ["InMemoryWorkflowBindingStore", "InMemoryWorkflowDefinitionStore"]
