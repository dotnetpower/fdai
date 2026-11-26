from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.delivery.persistence.postgres_workflow_definition import (
    _same_definition_except_created_at,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowDefinitionRecord,
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _definition() -> WorkflowDefinitionRecord:
    return WorkflowDefinitionRecord(
        definition_id="workflow-definition:example",
        workflow_name="example",
        workflow_version="1",
        schema_version="1",
        definition_hash="sha256:definition",
        action_catalog_digest="sha256:actions",
        resolved_action_versions={"tool.example": "1"},
        workflow_document={"name": "example"},
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        lifecycle=WorkflowLifecycle.SHADOW,
        created_at=NOW,
        source_ref="catalog:example@1",
    )


def test_restart_seed_ignores_only_created_at() -> None:
    existing = _definition()
    restarted = replace(existing, created_at=NOW + timedelta(hours=1))

    assert _same_definition_except_created_at(existing, restarted)


def test_restart_seed_rejects_immutable_metadata_change() -> None:
    existing = _definition()
    changed = replace(
        existing,
        created_at=NOW + timedelta(hours=1),
        lifecycle=WorkflowLifecycle.PUBLISHED,
    )

    assert not _same_definition_except_created_at(existing, changed)
