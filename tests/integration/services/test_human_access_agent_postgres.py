"""Real fixed-agent enforce handoffs over actual SQL safeguards and synthetic membership HTTP."""

from __future__ import annotations

import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fdai.agents import (
    AssignmentWorkflowBindings,
    PantheonRuntime,
    Saga,
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation
from fdai.runtime.providers import _safeguard_continuity_policy
from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC, EXECUTOR_RECEIPT_TOPIC
from fdai_service_contracts.executor import SafeguardBoundExecutorCommand

ROOT = Path(__file__).resolve().parents[3]
_support = runpy.run_path(str(Path(__file__).with_name("test_human_access_recovery_postgres.py")))
database, workflow = _support["database"], _support["workflow"]
_role, approve_original = _support["_role"], _support["approve_original"]
LiveBus = runpy.run_path(
    str(ROOT / "services/core-control-plane/tests/agents/test_runtime_chain.py")
)["LiveInMemoryEventBus"]
pytestmark = pytest.mark.integration


class AgentBus(LiveBus):
    """Bound event-driven test signals; no polling or successful fake executor callback."""

    def __init__(self, f):
        super().__init__()
        self.f = f
        self.receipt_saved = asyncio.Event()
        self.effect = asyncio.Event()
        self.inverse_waiting = asyncio.Event()
        self.recovered = asyncio.Event()
        self.inverse_action = None
        self.tasks = []

    async def publish(self, topic, key, payload):
        result = await super().publish(topic, key, payload)
        if topic == EXECUTOR_COMMAND_TOPIC:
            self.tasks.append(asyncio.create_task(self.deliver(payload)))
        step = payload.get("human_access", {})
        if topic == "object.state-snapshot" and step.get("stage") == "effect_recorded":
            self.effect.set()
        if (
            topic == "object.approval"
            and step.get("stage") == "awaiting_human"
            and step.get("action_id") != str(self.f.original.action().action_id)
        ):
            self.inverse_action = step["action_id"]
            self.inverse_waiting.set()
        if topic == "object.rollback" and step.get("stage") == "recovery_recorded":
            self.recovered.set()
        return result

    async def deliver(self, payload):
        command = SafeguardBoundExecutorCommand.model_validate(payload)
        receipt = await self.f.executor.handle(command)
        assert receipt.status.value == "dispatched", receipt.reason
        await self.publish(
            EXECUTOR_RECEIPT_TOPIC, command.partition_key, receipt.model_dump(mode="json")
        )


async def test_real_enforce_agents_and_vidar_inverse_without_t2_executor(workflow):
    f = workflow
    bus = AgentBus(f)
    f.runtime.dispatch_port.client.event_bus = bus
    save = f.runtime.store.write_state_with_audit_if_absent

    async def saved(key, value, entry):
        result = await save(key, value, entry)
        if key.startswith("runtime:isolated-executor:terminal-receipt:"):
            bus.receipt_saved.set()
        return result

    runtime = PantheonRuntime.build(
        provider=bus,
        raw_event_topic="human-access.agent-sql",
        enforce=True,
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(store=f.runtime.store)),
        thor_state_store=StateStoreActionRunStore(f.runtime.store),
        execution_resource_lock=PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn=_role(f.database, "fdai_core"),
                lock_timeout_ms=3000,
                continuity_policy=_safeguard_continuity_policy(),
            )
        ),
        approver_authorizer=lambda _person, _action: True,
        assignment_workflow=AssignmentWorkflowBindings(
            AsyncMock(),
            AsyncMock(),
            SimpleNamespace(apply=AsyncMock()),
            human_access=f.runtime.agent_bindings(),
        ),
    )
    worker = HumanAccessReconciliation(f.runtime, runtime.ingest_raw_event)
    run = asyncio.create_task(runtime.run())
    try:
        with patch.object(f.runtime.store, "write_state_with_audit_if_absent", saved):
            await worker.decision(f.original.approval_ids[0])
            await asyncio.wait_for(bus.receipt_saved.wait(), timeout=15)
            await worker.tick()
            await asyncio.wait_for(bus.effect.wait(), timeout=15)
            case = await f.runtime.builder.cases.get_case(f.notice.case_id)
            assert case.state.value == "active"
            await f.runtime.builder.cases.mark_degraded(
                case_id=case.case_id,
                expected_revision=case.revision,
                reason_code="reviewed_recovery_required",
                actor_ref="Muninn",
                now=f.runtime.clock(),
            )
            await worker.tick()
            await asyncio.wait_for(bus.inverse_waiting.wait(), timeout=15)
            inverse = await f.runtime.builder.materials.read(bus.inverse_action)
            assert inverse.inverse is not None
            assert f.membership["membership"] is True
            await approve_original(f.database, f.runtime, inverse)
            bus.receipt_saved.clear()
            await worker.decision(inverse.approval_ids[0])
            await asyncio.wait_for(bus.receipt_saved.wait(), timeout=15)
            await worker.tick()
            await asyncio.wait_for(bus.recovered.wait(), timeout=15)
        assert f.membership["membership"] is False
        assert (await f.runtime.builder.cases.get_case(f.notice.case_id)).state.value == "degraded"
        assert [r.method for r in f.requests if r.method != "GET"] == ["POST", "DELETE"]
        assert not any(records for topic, records in bus._records.items() if topic.endswith(".dlq"))
        rollback_owners = {
            payload["producer_principal"] for _, payload in bus._records["object.rollback"]
        }
        assert rollback_owners == {"Vidar"}
        with pytest.raises(RuntimeError, match="general Thor execution is unbound"):
            await runtime.agents["Thor"]._executor({})
    finally:
        await runtime.stop()
        run.cancel()
        await asyncio.gather(run, *bus.tasks, return_exceptions=True)
