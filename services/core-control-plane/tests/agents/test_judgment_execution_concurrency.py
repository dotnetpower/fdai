from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.forseti import Forseti
from fdai.agents.thor import Thor
from fdai.agents.vidar import RollbackRecord, Vidar, _rollback_state_key
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), isolate_handlers=False)


def _auto_verdict(correlation_id: str, resource_id: str) -> dict[str, Any]:
    return {
        "producer_principal": "Forseti",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:verdict",
        "action_idempotency_key": f"{correlation_id}:action",
        "action_type": "ops.restart-service",
        "risk_verdict": "auto",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
        "resource_id": resource_id,
        "rollback_contract": "state_forward_only",
    }


def _approval_for(run: ActionRun) -> dict[str, Any]:
    return {
        "producer_principal": "Var",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"{run.correlation_id}:approval",
        "action_idempotency_key": run.idempotency_key,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_id": run.action_id,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "rollback_contract": run.rollback_contract,
        "state": "approved",
    }


def _failed_action_run(correlation_id: str, *, contract: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:failed",
        "action_idempotency_key": f"{correlation_id}:action",
        "action_type": "ops.restart-service",
        "resource_id": f"resource:{correlation_id}",
        "state": "failed",
        "verdict": "auto",
        "params": {},
        "quorum_required": 1,
        "rollback_contract": contract,
    }
    payload["action_run_identity"] = action_run_identity_digest(payload)
    return payload


def _candidate(topic: str, correlation_id: str, *, utility: float) -> dict[str, Any]:
    principal = {
        "object.cost-anomaly": "Njord",
        "object.drift": "Heimdall",
        "object.resilience-score": "Loki",
    }[topic]
    payload: dict[str, Any] = {
        "producer_principal": principal,
        "kind": "cross_vertical_candidate",
        "topic": topic,
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:{topic}",
        "resource_id": "resource:shared",
        "observed_at": _NOW.isoformat(),
        "action_type": "ops.restart-service",
        "effects": [
            {
                "objective_id": "availability",
                "metric": "availability",
                "observation_window_seconds": 60,
                "utility": utility,
                "confidence": 0.9,
                "expected_min": 0.0,
                "expected_max": 1.0,
            }
        ],
        "evidence_refs": [f"evidence:{topic}"],
    }
    if topic == "object.resilience-score":
        payload["score"] = 0.5
    return payload


async def test_thor_resource_contention_is_visible_while_executor_blocks() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def executor(_command: dict[str, Any]) -> bool:
        started.set()
        await release.wait()
        return True

    thor = Thor(bus=_bus(), executor=executor)
    first = asyncio.create_task(thor.dispatch_verdict(_auto_verdict("corr-1", "resource-1")))
    await asyncio.wait_for(started.wait(), timeout=1)

    second = await asyncio.wait_for(
        thor.dispatch_verdict(_auto_verdict("corr-2", "resource-1")),
        timeout=0.2,
    )

    assert second.state is ActionRunState.DENY_DROPPED
    assert second.outcome == "resource_active_action_run_contention"
    release.set()
    await first


async def test_thor_duplicate_approval_does_not_wait_for_executor() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def executor(_command: dict[str, Any]) -> bool:
        started.set()
        await release.wait()
        return True

    thor = Thor(bus=_bus(), executor=executor)
    run = await thor.dispatch_verdict(
        {**_auto_verdict("corr-hil", "resource-hil"), "risk_verdict": "hil"}
    )
    approval = _approval_for(run)
    executing = asyncio.create_task(thor.on_typed_message("object.approval", approval))
    await asyncio.wait_for(started.wait(), timeout=1)

    await asyncio.wait_for(thor.on_typed_message("object.approval", approval), timeout=0.2)

    assert thor.behavior_snapshot()["approval:duplicate"] >= 1
    release.set()
    await executing


async def test_thor_execution_audit_timeout_denies_before_executor_io() -> None:
    executor_called = False
    never = asyncio.Event()

    async def recorder(_run: ActionRun) -> str:
        await never.wait()
        return "audit:receipt"

    async def executor(_command: dict[str, Any]) -> bool:
        nonlocal executor_called
        executor_called = True
        return True

    thor = Thor(
        bus=_bus(),
        executor=executor,
        execution_audit_recorder=recorder,
        require_execution_audit=True,
        execution_audit_timeout_seconds=0.01,
    )

    run = await thor.dispatch_verdict(_auto_verdict("corr-audit", "resource-audit"))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "execution_audit_timeout"
    assert executor_called is False
    assert thor.behavior_snapshot()["execution_audit:timeout"] == 1


async def test_thor_releases_resource_claim_before_deleting_terminal_state() -> None:
    events: list[str] = []

    class _Store:
        async def save(self, _run: ActionRun) -> None:
            return None

        async def load_active(self) -> list[ActionRun]:
            return []

        async def delete(self, _correlation_id: str) -> None:
            events.append("delete")

        async def refresh_resource_claim(self, _run: ActionRun) -> bool:
            return True

        async def release_resource(self, _resource_id: str, _correlation_id: str) -> bool:
            events.append("release")
            return True

    run = ActionRun(
        correlation_id="corr-release",
        action_type="ops.restart-service",
        resource_id="resource-release",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        idempotency_key="corr-release:action",
        terminal_published=True,
    )
    run.resource_claimed = True
    thor = Thor(state_store=_Store())  # type: ignore[arg-type]

    await thor._release_resource_claim(run)  # noqa: SLF001

    assert events == ["release", "delete"]
    assert run.resource_claimed is False


async def test_thor_approval_expiry_finishes_after_cancellation() -> None:
    save_entered = asyncio.Event()
    release_save = asyncio.Event()
    released = asyncio.Event()

    class _Store:
        async def save(self, run: ActionRun) -> None:
            if run.state is ActionRunState.REJECTED:
                save_entered.set()
                await release_save.wait()

        async def load_active(self) -> list[ActionRun]:
            return []

        async def delete(self, _correlation_id: str) -> None:
            return None

        async def claim_resource(self, run: ActionRun) -> str:
            run.resource_claimed = True
            return "acquired"

        async def release_resource(self, _resource_id: str, _correlation_id: str) -> bool:
            released.set()
            return True

    thor = Thor(state_store=_Store())  # type: ignore[arg-type]
    run = ActionRun(
        correlation_id="corr-expire-cancel",
        action_type="ops.restart-service",
        resource_id="resource-expire-cancel",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        idempotency_key="corr-expire-cancel:action",
        approval_expires_at=_NOW,
    )
    thor.action_runs[run.correlation_id] = run

    task = asyncio.create_task(thor._expire_approval(run))  # noqa: SLF001
    await asyncio.wait_for(save_entered.wait(), timeout=1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    release_save.set()
    await asyncio.wait_for(released.wait(), timeout=1)

    assert run.state is ActionRunState.REJECTED
    assert run.outcome == "approval_expired"
    assert run.resource_claimed is False


async def test_thor_terminal_checkpoint_finishes_after_cancellation() -> None:
    save_entered = asyncio.Event()
    release_save = asyncio.Event()

    class _Bus:
        async def publish(
            self,
            _principal: str,
            _topic: str,
            _payload: Mapping[str, Any],
        ) -> None:
            return None

    class _Store:
        async def save(self, run: ActionRun) -> None:
            if run.state is ActionRunState.SUCCEEDED and run.terminal_published:
                save_entered.set()
                await release_save.wait()

        async def load_active(self) -> list[ActionRun]:
            return []

        async def delete(self, _correlation_id: str) -> None:
            return None

    run = ActionRun(
        correlation_id="corr-terminal-cancel",
        action_type="ops.restart-service",
        resource_id="resource-terminal-cancel",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        idempotency_key="corr-terminal-cancel:action",
    )
    thor = Thor(bus=_Bus(), state_store=_Store())  # type: ignore[arg-type]

    task = asyncio.create_task(thor._emit_action_run(run))  # noqa: SLF001
    await asyncio.wait_for(save_entered.wait(), timeout=1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    release_save.set()
    for _ in range(10):
        await asyncio.sleep(0)
        if run.terminal_published:
            break

    assert run.terminal_published is True


async def test_vidar_unrelated_rollback_is_not_blocked_by_slow_executor() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_command: dict[str, Any]) -> str:
        started.set()
        await release.wait()
        return "rollback:slow"

    vidar = Vidar(bus=_bus(), executors={"slow": slow}, allow_process_local_rollback=True)
    first = asyncio.create_task(vidar.rollback(_failed_action_run("rollback-1", contract="slow")))
    await asyncio.wait_for(started.wait(), timeout=1)

    second = await asyncio.wait_for(
        vidar.rollback(_failed_action_run("rollback-2", contract="missing")),
        timeout=0.2,
    )

    assert second is not None
    assert second.state == "failed"
    release.set()
    await first


async def test_vidar_executor_timeout_records_execution_unknown() -> None:
    never = asyncio.Event()

    async def slow(_command: dict[str, Any]) -> str:
        await never.wait()
        return "rollback:late"

    vidar = Vidar(
        bus=_bus(),
        executors={"slow": slow},
        allow_process_local_rollback=True,
        rollback_executor_timeout_seconds=0.01,
    )

    rec = await vidar.rollback(_failed_action_run("rollback-timeout", contract="slow"))

    assert rec is not None
    assert rec.state == "execution_unknown"
    assert rec.notes == "rollback executor timed out before terminal receipt"


async def test_vidar_cancellation_after_claim_records_unknown_terminal_receipt() -> None:
    entered = asyncio.Event()
    never = asyncio.Event()
    store = InMemoryStateStore()

    async def slow(_command: dict[str, Any]) -> str:
        entered.set()
        await never.wait()
        return "rollback:late"

    action_run = _failed_action_run("rollback-cancel", contract="slow")
    vidar = Vidar(bus=_bus(), executors={"slow": slow}, state_store=store)
    task = asyncio.create_task(vidar.rollback(action_run))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    row = await store.read_state(
        _rollback_state_key(
            "rollback-cancel",
            "state",
            str(action_run["action_run_identity"]),
        )
    )
    assert row is not None
    assert row["status"] == "terminal"
    assert row["state"] == "execution_unknown"


async def test_vidar_concurrent_publication_claim_allows_one_publish() -> None:
    class _YieldingBus(InMemoryBus):
        async def publish(
            self,
            principal: str,
            topic: str,
            payload: Mapping[str, Any],
        ) -> None:
            await asyncio.sleep(0)
            await super().publish(principal, topic, dict(payload))

    store = InMemoryStateStore()
    bus = _YieldingBus(registry=load_pantheon(), isolate_handlers=False)
    vidar = Vidar(bus=bus, state_store=store)
    action_run = _failed_action_run("rollback-publish", contract="missing")
    rec = RollbackRecord(
        correlation_id="rollback-publish",
        action_run_identity=str(action_run["action_run_identity"]),
        action_type="ops.restart-service",
        resource_id="resource:rollback-publish",
        contract="missing",
        state="failed",
        notes="test rollback",
    )

    await asyncio.gather(vidar._publish_rollback_once(rec), vidar._publish_rollback_once(rec))  # noqa: SLF001

    assert len(bus.messages_on("object.rollback")) == 1


async def test_forseti_concurrent_pending_candidates_persist_once() -> None:
    class _CountingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.pending_writes = 0

        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            if key.startswith("pantheon/forseti/cross-vertical-pending|"):
                self.pending_writes += 1
            return await super().write_state_if_absent(key, value)

    store = _CountingStore()
    forseti = Forseti(bus=_bus(), state_store=store, test_context_clock=lambda: _NOW)

    await asyncio.gather(
        forseti.on_typed_message(
            "object.cost-anomaly",
            _candidate("object.cost-anomaly", "candidate-corr", utility=0.2),
        ),
        forseti.on_typed_message(
            "object.drift",
            _candidate("object.drift", "candidate-corr", utility=0.3),
        ),
    )

    assert store.pending_writes == 1


async def test_forseti_timeout_task_exception_is_observed() -> None:
    forseti = Forseti(cross_vertical_timeout_seconds=0.01)

    async def fail_close(_closures: tuple[Any, ...]) -> None:
        raise RuntimeError("injected close failure")

    forseti._close_cross_vertical_candidates = fail_close  # type: ignore[method-assign]  # noqa: SLF001

    await forseti.on_typed_message(
        "object.cost-anomaly",
        _candidate("object.cost-anomaly", "candidate-timeout-error", utility=0.2),
    )
    for _ in range(100):
        await asyncio.sleep(0.01)
        if forseti.behavior_snapshot().get("cross_vertical_timeout:failed") == 1:
            break

    assert forseti.behavior_snapshot()["cross_vertical_timeout:failed"] == 1


async def test_forseti_architecture_review_timeout_publishes_hold() -> None:
    class _Loop:
        async def evaluate(self, _payload: dict[str, Any]) -> Any:
            await asyncio.Event().wait()

    bus = _bus()
    forseti = Forseti(
        bus=bus,
        architecture_review_loop=_Loop(),  # type: ignore[arg-type]
        architecture_review_timeout_seconds=0.01,
    )

    await forseti.on_typed_message(
        "object.change",
        {
            "producer_principal": "Huginn",
            "id": "change-timeout",
            "correlation_id": "corr-change-timeout",
            "idempotency_key": "change-timeout:key",
            "target_ref": "resource-change",
        },
    )

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["correlation_id"] == "corr-change-timeout"
    assert verdict["idempotency_key"] == "change-timeout:key"
    assert verdict["reasons"] == ["observation_review_timeout"]
    assert forseti.behavior_snapshot()["architecture_review:timeout"] == 1


async def test_forseti_change_assessment_timeout_fails_closed() -> None:
    class _Context:
        async def materialize(self, **_kwargs: Any) -> Any:
            await asyncio.Event().wait()

    class _Assessor:
        async def assess(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("assessment should not run after evidence timeout")

    event = {
        "producer_principal": "Huginn",
        "event_type": "change.detected",
        "correlation_id": "change-assess-timeout",
        "idempotency_key": "change-assess-timeout:key",
        "resource_id": "resource-change",
        "normalized_change": {
            "intent_kind": "planned",
            "target_ref": "resource-change",
            "occurred_at": _NOW.isoformat(),
            "ontology_release_digest": "sha256:" + "a" * 64,
        },
    }
    forseti = Forseti(
        operational_context=_Context(),  # type: ignore[arg-type]
        change_assessor=_Assessor(),  # type: ignore[arg-type]
        change_assessment_timeout_seconds=0.01,
    )

    await forseti.on_typed_message("object.event", event)

    assert event["change_assessment_status"] == "failed"
    assert event["human_approval_required"] is True
    assert forseti.behavior_snapshot()["change_assessment:timeout"] == 1
