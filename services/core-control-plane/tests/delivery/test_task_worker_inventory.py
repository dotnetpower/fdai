from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fdai.core.task_worker.tools import TaskWorkerToolDeniedError
from fdai.delivery.task_worker_inventory import TaskWorkerInventoryTool, TaskWorkerReadScope
from fdai.shared.providers.read_investigation import ReadToolId


def _record():
    return {
        "snapshot_id": "snapshot:one",
        "observed_at": "2026-09-15T12:00:00Z",
        "resource_id": "resource:one",
        "name": "example-vm",
        "resource_type": "Compute",
        "state": "running",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"resource_ref": "resource:other"},
        {"resource_ref": "resource:one", "query": "arbitrary"},
    ],
)
async def test_tool_rejects_unreviewed_scope_before_source_read(arguments):
    reader = AsyncMock()
    tool = TaskWorkerInventoryTool(
        tool_id=ReadToolId.GET_RESOURCE_STATE,
        scope=TaskWorkerReadScope("scope:one", frozenset({"resource:one"})),
        reader=reader,
    )
    with pytest.raises(TaskWorkerToolDeniedError):
        await tool.call(arguments)
    reader.assert_not_awaited()


@pytest.mark.parametrize("tool_id", list(ReadToolId))
async def test_registry_reads_only_exact_recorded_inventory_and_preserves_unavailable(tool_id):
    reader = AsyncMock(return_value=_record())
    tool = TaskWorkerInventoryTool(
        tool_id=tool_id,
        scope=TaskWorkerReadScope("scope:one", frozenset({"resource:one"})),
        reader=reader,
    )
    result = await tool.call({"resource_ref": "resource:one"})
    assert tool.side_effect_class == "read"
    if tool_id in {ReadToolId.RESOLVE_RESOURCE, ReadToolId.GET_RESOURCE_STATE}:
        assert dict(result.data)["resource_ref"] == "resource:one"
        reader.assert_awaited_once_with("resource:one")
        if tool_id is ReadToolId.GET_RESOURCE_STATE:
            assert dict(result.data)["state_0"] == "running"
            assert result.evidence_refs == ("inventory-snapshot:snapshot:one",)
    else:
        assert dict(result.data) == {"status": "unavailable", "reason": "source_unbound"}
        assert result.evidence_refs == ()
        reader.assert_not_awaited()


@pytest.mark.parametrize(
    "record",
    [None, {**_record(), "snapshot_id": None}, {**_record(), "observed_at": "2026-09-15T12:00:00"}],
)
async def test_incomplete_source_cannot_become_current_worker_evidence(record):
    reader = AsyncMock(return_value=record)
    tool = TaskWorkerInventoryTool(
        tool_id=ReadToolId.GET_RESOURCE_STATE,
        scope=TaskWorkerReadScope("scope:one", frozenset({"resource:one"})),
        reader=reader,
    )
    assert dict((await tool.call({"resource_ref": "resource:one"})).data)["status"] == "unavailable"
    reader.assert_awaited_once_with("resource:one")


async def test_source_cannot_substitute_another_resource():
    reader = AsyncMock(return_value={**_record(), "resource_id": "resource:other"})
    tool = TaskWorkerInventoryTool(
        tool_id=ReadToolId.GET_RESOURCE_STATE,
        scope=TaskWorkerReadScope("scope:one", frozenset({"resource:one"})),
        reader=reader,
    )
    with pytest.raises(TaskWorkerToolDeniedError, match="does not match"):
        await tool.call({"resource_ref": "resource:one"})


@pytest.mark.parametrize("resources", [[], ["*"], ["resource:one", "resource:one"], [False]])
def test_private_scope_rejects_empty_wildcard_duplicate_or_malformed_resources(resources):
    with pytest.raises(ValueError):
        TaskWorkerReadScope.from_json(
            json.dumps({"scope_ref": "scope:one", "resource_refs": resources})
        )
