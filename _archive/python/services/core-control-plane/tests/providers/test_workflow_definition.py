from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.shared.providers.testing.workflow_definition import (
    InMemoryWorkflowBindingStore,
    InMemoryWorkflowDefinitionStore,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowBindingRecord,
    WorkflowBindingTrigger,
    WorkflowDefinitionConflictError,
    WorkflowDefinitionRecord,
    WorkflowLifecycle,
    WorkflowOrigin,
    WorkflowVisibility,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _definition(
    *,
    definition_id: str,
    origin: WorkflowOrigin,
    visibility: WorkflowVisibility,
    owner_ref: str | None,
) -> WorkflowDefinitionRecord:
    return WorkflowDefinitionRecord(
        definition_id=definition_id,
        workflow_name="major-issue-briefing",
        workflow_version="1.0.0",
        schema_version="1.0.0",
        definition_hash="sha256:definition",
        action_catalog_digest="sha256:actions",
        resolved_action_versions={"tool.generate-pdf": "1.0.0"},
        workflow_document={"name": "major-issue-briefing", "steps": ["render"]},
        origin=origin,
        visibility=visibility,
        lifecycle=WorkflowLifecycle.SHADOW,
        owner_ref=owner_ref,
        created_at=NOW,
    )


async def test_definition_visibility_is_principal_and_team_scoped() -> None:
    store = InMemoryWorkflowDefinitionStore()
    builtin = _definition(
        definition_id="builtin",
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        owner_ref=None,
    )
    private = _definition(
        definition_id="private",
        origin=WorkflowOrigin.USER,
        visibility=WorkflowVisibility.PRIVATE,
        owner_ref="principal-a",
    )
    shared = _definition(
        definition_id="shared",
        origin=WorkflowOrigin.TENANT,
        visibility=WorkflowVisibility.TEAM,
        owner_ref="team-ops",
    )
    for definition in (builtin, private, shared):
        await store.put(definition)

    visible = await store.list_visible(principal_id="principal-a", team_refs=("team-ops",))
    assert {item.definition_id for item in visible} == {"builtin", "private", "shared"}
    other = await store.list_visible(principal_id="principal-b")
    assert tuple(item.definition_id for item in other) == ("builtin",)


async def test_definition_is_immutable() -> None:
    store = InMemoryWorkflowDefinitionStore()
    record = _definition(
        definition_id="builtin",
        origin=WorkflowOrigin.UPSTREAM,
        visibility=WorkflowVisibility.GLOBAL,
        owner_ref=None,
    )
    await store.put(record)
    with pytest.raises(WorkflowDefinitionConflictError, match="immutable"):
        await store.put(replace(record, lifecycle=WorkflowLifecycle.PUBLISHED))


async def test_binding_is_principal_scoped_and_optimistically_versioned() -> None:
    store = InMemoryWorkflowBindingStore()
    binding = WorkflowBindingRecord(
        binding_id="binding-1",
        principal_id="principal-a",
        definition_id="builtin",
        trigger=WorkflowBindingTrigger.SCHEDULE,
        cron_expression="0 7 * * *",
        timezone="Asia/Seoul",
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )
    created = await store.create(binding)
    assert created.revision == 1
    assert await store.list_for_principal(principal_id="principal-b") == ()
    updated = await store.put(replace(created, enabled=False), expected_revision=1)
    assert updated.revision == 2
    with pytest.raises(WorkflowDefinitionConflictError, match="revision mismatch"):
        await store.put(updated, expected_revision=1)


def test_user_definition_requires_owner() -> None:
    with pytest.raises(ValueError, match="owner_ref"):
        _definition(
            definition_id="invalid",
            origin=WorkflowOrigin.USER,
            visibility=WorkflowVisibility.PRIVATE,
            owner_ref=None,
        )
