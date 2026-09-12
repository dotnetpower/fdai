"""Automation-hold checks at the isolated provider boundary."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fdai_executor_service.effect_executor import (
    DirectApiEffectOutcome,
    ServiceDirectApiEffectExecutor,
)
from fdai_executor_service.effect_safety import resource_lock_key
from fdai_service_contracts.executor import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    DirectApiOutcome,
    DirectApiReceipt,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai_service_contracts.executor_models import WorkflowActionRef

_NOW = datetime(2026, 9, 11, tzinfo=UTC)
_TARGET = "/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app"


class _Lock:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self.active: set[str] = set()

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(resource_id, asyncio.Lock())
        async with lock:
            self.active.add(resource_id)
            try:
                yield
            finally:
                self.active.remove(resource_id)


class _StateStore:
    def __init__(self, records: Mapping[str, Mapping[str, Any]], lock: _Lock) -> None:
        self.records = dict(records)
        self.lock = lock
        self.audit: list[Mapping[str, Any]] = []

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        self.audit.append(dict(entry))

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        if key.startswith("workflow:automation-hold"):
            assert resource_lock_key(_TARGET) in self.lock.active
        return self.records.get(key)


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _request: object) -> DirectApiReceipt:
        self.calls += 1
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref="provider:receipt",
        )


def _action(*, with_workflow: bool = False) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID(int=1),
        idempotency_key="hold-fence",
        event_id=UUID(int=2),
        action_type="ops.start-vm",
        target_resource_ref=_TARGET,
        operation=Operation.ENABLE,
        params={"resource_group": "example", "vm_name": "vm-app"},
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=60)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["rule.example"],
        created_at=_NOW,
        workflow_action=(
            WorkflowActionRef(
                process_id="process-1",
                step_id="recover_" + "a" * 32,
                proposal_ref="proposal:recovery",
            )
            if with_workflow
            else None
        ),
    )


def _hold_key() -> str:
    return "workflow:automation-hold:" + hashlib.sha256(_TARGET.encode()).hexdigest()


def _authorization_key(action: Action) -> str:
    workflow = action.workflow_action
    assert workflow is not None
    target_digest = hashlib.sha256(_TARGET.encode()).hexdigest()
    identity = f"{target_digest}\0{workflow.process_id}\0{workflow.step_id}"
    return (
        "workflow:automation-hold-dispatch-authorization:"
        + hashlib.sha256(identity.encode()).hexdigest()
    )


async def test_active_hold_blocks_provider_inside_the_target_lock() -> None:
    lock = _Lock()
    target_digest = hashlib.sha256(_TARGET.encode()).hexdigest()
    store = _StateStore(
        {
            _hold_key(): {
                "target_digest": target_digest,
                "process_id": "process-1",
                "state": "active",
                "revision": 1,
            }
        },
        lock,
    )
    provider = _Provider()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=store,  # type: ignore[arg-type]
        resource_lock=lock,
        idempotency=None,
        allow_enforce=True,
        clock=lambda: _NOW,
    )

    result = await executor.execute(action=_action())

    assert result.outcome is DirectApiEffectOutcome.REJECTED_INVARIANT
    assert result.reason == "active automation hold blocks provider invocation"
    assert provider.calls == 0


async def test_released_hold_is_rechecked_instead_of_replaying_cached_denial() -> None:
    lock = _Lock()
    target_digest = hashlib.sha256(_TARGET.encode()).hexdigest()
    store = _StateStore(
        {
            _hold_key(): {
                "target_digest": target_digest,
                "process_id": "process-1",
                "state": "active",
                "revision": 1,
            }
        },
        lock,
    )
    provider = _Provider()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=store,  # type: ignore[arg-type]
        resource_lock=lock,
        idempotency=None,
        allow_enforce=True,
        clock=lambda: _NOW,
    )

    denied = await executor.execute(action=_action())
    store.records[_hold_key()] = {
        "target_digest": target_digest,
        "process_id": "process-1",
        "state": "released",
        "revision": 2,
    }
    retried = await executor.execute(action=_action())

    assert denied.outcome is DirectApiEffectOutcome.REJECTED_INVARIANT
    assert retried.outcome is DirectApiEffectOutcome.DISPATCHED
    assert provider.calls == 1


async def test_exact_hold_scoped_authorization_allows_recovery_dispatch() -> None:
    action = _action(with_workflow=True)
    lock = _Lock()
    target_digest = hashlib.sha256(_TARGET.encode()).hexdigest()
    store = _StateStore(
        {
            _hold_key(): {
                "target_digest": target_digest,
                "process_id": "process-1",
                "state": "active",
                "revision": 3,
            },
            _authorization_key(action): {
                "target_digest": f"sha256:{target_digest}",
                "authorization_kind": "hold_scoped",
                "process_id": "process-1",
                "step_id": "recover_" + "a" * 32,
                "authorized_hold_revision": 3,
                "execution_authority": False,
                "revision": 1,
            },
        },
        lock,
    )
    provider = _Provider()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=store,  # type: ignore[arg-type]
        resource_lock=lock,
        idempotency=None,
        allow_enforce=True,
        clock=lambda: _NOW,
    )

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiEffectOutcome.DISPATCHED
    assert provider.calls == 1


async def test_malformed_hold_revision_never_authorizes_dispatch() -> None:
    action = _action(with_workflow=True)
    lock = _Lock()
    target_digest = hashlib.sha256(_TARGET.encode()).hexdigest()
    store = _StateStore(
        {
            _hold_key(): {
                "target_digest": target_digest,
                "process_id": "process-1",
                "state": "active",
                "revision": 1,
            },
            _authorization_key(action): {
                "target_digest": f"sha256:{target_digest}",
                "authorization_kind": "hold_scoped",
                "process_id": "process-1",
                "step_id": "recover_" + "a" * 32,
                "authorized_hold_revision": True,
                "execution_authority": False,
                "revision": 1,
            },
        },
        lock,
    )
    provider = _Provider()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=store,  # type: ignore[arg-type]
        resource_lock=lock,
        idempotency=None,
        allow_enforce=True,
        clock=lambda: _NOW,
    )

    result = await executor.execute(action=action)

    assert result.outcome is DirectApiEffectOutcome.REJECTED_INVARIANT
    assert result.reason == "active automation hold lacks exact recovery-step authorization"
    assert provider.calls == 0
