"""Workflow pre-bundle commitment persistence and dispatch evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.executor.safeguard_pre_bundle import SafeguardPreBundleCommitment
from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.safeguard_commitment import (
    ProcessRuntimeSafeguardCommitmentStore,
)
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import ExecutionPath, WorkflowActionRef
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

from tests.core.executor.test_direct_api_executor import _action

_NOW = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40


async def _process_store() -> InMemoryProcessRuntimeStore:
    store = InMemoryProcessRuntimeStore()
    await store.create(
        snapshot=ProcessSnapshot(
            process_id="process-1",
            workflow_ref="workflow-1",
            workflow_version="1.0.0",
            status=ProcessStatus.RUNNING,
            current_step="restart",
            target_resource_id="resource-1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="correlation-1",
        ),
        event=ProcessEvent(
            event_id="process-1:created",
            process_id="process-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="process-1:created",
            recorded_at=_NOW,
            correlation_id="correlation-1",
        ),
    )
    return store


async def test_commitment_is_immutable_and_precedes_dispatch_event() -> None:
    process_store = await _process_store()
    await process_store.append_event(
        ProcessEvent(
            event_id="process-1:approval:2",
            process_id="process-1",
            kind=ProcessEventKind.APPROVAL_RECORDED,
            idempotency_key="process-1:approval:2",
            recorded_at=_NOW,
            correlation_id="correlation-1",
            step_id="approve",
            attempt=2,
            payload={"decision": "approved"},
        )
    )
    store = ProcessRuntimeSafeguardCommitmentStore(process_store)
    action = _action().model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id="process-1",
                step_id="restart",
                proposal_ref="process-1:step:restart:attempt:2",
                attempt=2,
            )
        }
    )
    commitment = SafeguardPreBundleCommitment.create(
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        source_revision=_SOURCE_REVISION,
        committed_at=_NOW,
    )

    first = await store.bind(
        process_id="process-1",
        step_id="restart",
        attempt=2,
        correlation_id="correlation-1",
        commitment=commitment,
    )
    replay = await store.bind(
        process_id="process-1",
        step_id="restart",
        attempt=2,
        correlation_id="correlation-1",
        commitment=commitment,
    )

    assert replay == first
    events = await process_store.events("process-1")
    committed = [
        event for event in events if event.kind is ProcessEventKind.ACTION_PRE_BUNDLE_COMMITTED
    ]
    assert len(committed) == 1
    assert committed[0].payload["commitment"]["commitment_digest"] == commitment.commitment_digest
    assert committed[0].payload["approval_event_ids"] == ("process-1:approval:2",)

    changed = SafeguardPreBundleCommitment.create(
        action=action,
        execution_path=ExecutionPath.PR_NATIVE,
        source_revision=_SOURCE_REVISION,
        committed_at=_NOW,
    )
    with pytest.raises(RuntimeError, match="conflicts"):
        await store.bind(
            process_id="process-1",
            step_id="restart",
            attempt=2,
            correlation_id="correlation-1",
            commitment=changed,
        )


async def test_event_bus_dispatch_carries_exact_workflow_attempt() -> None:
    bus = InMemoryEventBus()
    dispatcher = EventBusWorkflowActionDispatcher(event_bus=bus, topic="fdai.events")

    proposal_ref = await dispatcher.dispatch(
        process_id="process-1",
        correlation_id="correlation-1",
        step=RunbookStep(id="restart", action_type="ops.restart-service"),
        target_resource_id="resource-1",
        params={"cooldown_seconds": 30},
        context={"workflow.requester_principal": "operator-1"},
        attempt=3,
    )

    events = [item async for item in bus.subscribe("fdai.events", "test")]
    assert proposal_ref == "process-1:step:restart:attempt:3"
    assert len(events) == 1
    assert events[0].payload["workflow_action"] == {
        "process_id": "process-1",
        "step_id": "restart",
        "proposal_ref": proposal_ref,
        "attempt": 3,
    }
