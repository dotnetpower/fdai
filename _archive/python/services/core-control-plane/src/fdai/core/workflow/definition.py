"""Compile validated Workflows into immutable, version-pinned definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime

from fdai.shared.contracts.models import OntologyActionType, Workflow
from fdai.shared.providers.workflow_definition import (
    WorkflowDefinitionRecord,
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)


def built_in_workflow_lifecycle(
    workflow_name: str, *, promoted_workflows: frozenset[str]
) -> WorkflowLifecycle:
    """Resolve a built-in definition from the shared promotion configuration."""
    if workflow_name in promoted_workflows:
        return WorkflowLifecycle.PUBLISHED
    return WorkflowLifecycle.SHADOW


def build_workflow_definition(
    workflow: Workflow,
    *,
    action_types: Mapping[str, OntologyActionType],
    origin: WorkflowOrigin,
    visibility: WorkflowVisibility,
    lifecycle: WorkflowLifecycle,
    created_at: datetime,
    owner_ref: str | None = None,
    derived_from: str | None = None,
    source_ref: str | None = None,
) -> WorkflowDefinitionRecord:
    """Resolve every ActionType and freeze a canonical workflow artifact."""
    action_refs = {
        ref
        for step in workflow.steps
        for ref in (step.action_type_ref, step.compensated_by)
        if ref is not None
    }
    missing = sorted(action_refs - set(action_types))
    if missing:
        raise ValueError(f"workflow references unknown ActionTypes: {', '.join(missing)}")
    resolved_versions = {name: str(action_types[name].version) for name in sorted(action_refs)}
    document = workflow.model_dump(mode="json", exclude_none=True)
    document_json = _canonical(document)
    definition_hash = "sha256:" + hashlib.sha256(document_json.encode()).hexdigest()
    catalog_payload = [
        action_types[name].model_dump(mode="json", exclude_none=True)
        for name in sorted(action_types)
    ]
    action_catalog_digest = (
        "sha256:" + hashlib.sha256(_canonical(catalog_payload).encode()).hexdigest()
    )
    identity = {
        "workflow_name": workflow.name,
        "workflow_version": str(workflow.version),
        "definition_hash": definition_hash,
        "action_catalog_digest": action_catalog_digest,
        "resolved_action_versions": resolved_versions,
    }
    definition_id = (
        "workflow-definition:" + hashlib.sha256(_canonical(identity).encode()).hexdigest()[:32]
    )
    return WorkflowDefinitionRecord(
        definition_id=definition_id,
        workflow_name=workflow.name,
        workflow_version=str(workflow.version),
        schema_version=str(workflow.schema_version),
        definition_hash=definition_hash,
        action_catalog_digest=action_catalog_digest,
        resolved_action_versions=resolved_versions,
        workflow_document=document,
        origin=origin,
        visibility=visibility,
        lifecycle=lifecycle,
        owner_ref=owner_ref,
        derived_from=derived_from,
        source_ref=source_ref,
        created_at=created_at,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = ["build_workflow_definition", "built_in_workflow_lifecycle"]
