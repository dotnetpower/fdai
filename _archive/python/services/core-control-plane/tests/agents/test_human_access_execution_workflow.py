"""Declared-topic human-access choreography through the real Pantheon runtime."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment.model import AssignmentState
from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation

from tests.agents.test_runtime_chain import LiveInMemoryEventBus
from tests.runtime.test_human_access_workflow import setup as setup


class WorkflowBus(LiveInMemoryEventBus):
    def __init__(self):
        super().__init__()
        self.waiting = asyncio.Event()
        self.held = asyncio.Event()

    async def publish(self, topic, key, payload):
        receipt = await super().publish(topic, key, payload)
        if payload.get("human_access", {}).get("stage") == "awaiting_human":
            self.waiting.set()
        if payload.get("human_access", {}).get("reason") == "human_access_thor_safety_unavailable":
            self.held.set()
        return receipt


async def test_real_owner_chain_prepares_but_shadow_thor_cannot_dispatch(setup, monkeypatch):
    f = setup
    bus = WorkflowBus()
    runtime = PantheonRuntime.build(
        provider=bus,
        raw_event_topic="human-access.test.raw",
        assignment_workflow=AssignmentWorkflowBindings(
            AsyncMock(),
            AsyncMock(),
            SimpleNamespace(apply=AsyncMock()),
            human_access=f.runtime.agent_bindings(),
        ),
    )
    monkeypatch.setattr(runtime.agents["Huginn"], "_clock", lambda: f.clock["now"])
    worker = HumanAccessReconciliation(f.runtime, runtime.ingest_raw_event)
    task = asyncio.create_task(runtime.run())
    try:
        await worker.tick()
        await asyncio.wait_for(bus.waiting.wait(), timeout=3)
        rows, _ = await f.runtime.store.read_state_page(
            "human_assignment:execution-material:", limit=2
        )
        from fdai_service_contracts.human_access_execution import HumanAccessExecutionMaterial

        material = HumanAccessExecutionMaterial.model_validate(rows[0])
        slot = material.approval_ids[0]
        await f.runtime.store.write_state(
            "operator-hil-decision:" + slot,
            {
                "approval_id": slot,
                "idempotency_key": "human-access:" + slot,
                "approver_oid": "person:independent-owner",
                "decision": "approve",
                "decided_at": f.clock["now"].isoformat(),
                "receipt_ref": "operator:synthetic-decision",
            },
        )
        await worker.decision(slot)
        await asyncio.wait_for(bus.held.wait(), timeout=3)
        case = await f.runtime.builder.cases.get_case(f.case.case_id)
        assert case.state is AssignmentState.IAM_APPLYING
        assert case.iam_preparation.material_digest == material.digest
        assert not f.sent and not f.graph_requests
        owners = {
            topic: {
                record[1]["producer_principal"]
                for record in rows
                if record[1].get("kind") == "human_access_execution"
            }
            for topic, rows in bus._records.items()
            if not topic.endswith(".dlq")
        }
        assert owners["object.verdict"] == {"Forseti"}
        assert owners["object.approval"] == {"Var"}
        assert owners["object.state-snapshot"] == {"Muninn"}
        assert owners["object.audit-entry"] == {"Saga"}
        assert owners["object.action-run"] == {"Thor"}
        assert not any(rows for topic, rows in bus._records.items() if topic.endswith(".dlq"))
        for rows in bus._records.values():
            for _, payload in rows:
                if payload.get("kind") == "human_access_execution":
                    assert "subject_id" not in repr(payload) and "group:reader" not in repr(payload)
    finally:
        await runtime.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
