from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents import vidar as vidar_module
from fdai.agents._framework import action_run_identity as identity_module
from fdai.agents._framework import thor_action_run as thor_action_run_module
from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest,
    approval_matches_action_run,
)
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_durability import (
    _MAX_RESOURCES,
    rehydrate_arbitration_state,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.forseti import Forseti
from fdai.agents.thor import Thor
from fdai.agents.vidar import Vidar
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), isolate_handlers=False)


def _failed_action_run(correlation_id: str, *, payload_size: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:failed",
        "action_idempotency_key": f"{correlation_id}:action",
        "action_type": "ops.restart-service",
        "resource_id": f"resource:{correlation_id}",
        "state": "failed",
        "verdict": "auto",
        "params": {"items": list(range(payload_size))},
        "quorum_required": 1,
        "rollback_contract": "state_forward_only",
    }
    payload["action_run_identity"] = action_run_identity_digest(payload)
    return payload


def _candidate(topic: str, correlation_id: str) -> dict[str, Any]:
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
        "resource_id": f"resource:{correlation_id}",
        "observed_at": _NOW.isoformat(),
        "action_type": "ops.restart-service",
        "effects": [
            {
                "objective_id": "availability",
                "metric": "availability",
                "observation_window_seconds": 60,
                "utility": 0.2,
                "confidence": 0.9,
                "expected_min": 0.0,
                "expected_max": 1.0,
            }
        ],
        "evidence_refs": [f"evidence:{correlation_id}"],
    }
    if topic == "object.resilience-score":
        payload["score"] = 0.5
    return payload


async def test_thor_transition_publication_reuses_identity_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_calls = 0
    deepcopy_calls = 0
    original_digest = thor_action_run_module.action_run_identity_digest
    original_deepcopy = thor_action_run_module.deepcopy

    def counting_digest(value: Mapping[str, Any]) -> str:
        nonlocal identity_calls
        identity_calls += 1
        return original_digest(value)

    def counting_deepcopy(value: Any) -> Any:
        nonlocal deepcopy_calls
        deepcopy_calls += 1
        return original_deepcopy(value)

    monkeypatch.setattr(thor_action_run_module, "action_run_identity_digest", counting_digest)
    monkeypatch.setattr(thor_action_run_module, "deepcopy", counting_deepcopy)
    thor = Thor(bus=_bus())
    run = ActionRun(
        correlation_id="resource-bound-thor",
        action_type="ops.restart-service",
        resource_id="resource:thor",
        state=ActionRunState.VERDICTED,
        verdict="auto",
        idempotency_key="resource-bound-thor:action",
        params={"large": list(range(10_000))},
        operational_context={"large": list(range(10_000))},
    )

    await thor._emit_action_run(run)  # noqa: SLF001
    run.transition(ActionRunState.APPROVED)
    await thor._emit_action_run(run)  # noqa: SLF001
    run.transition(ActionRunState.SUCCEEDED)
    await thor._emit_action_run(run)  # noqa: SLF001

    payloads = [message.payload for message in thor.bus.messages_on("object.action-run")]
    assert len(payloads) == 3
    assert all(payload["correlation_id"] and payload["idempotency_key"] for payload in payloads)
    assert len({payload["action_run_identity"] for payload in payloads}) == 1
    assert identity_calls == 1
    assert deepcopy_calls == 6


def test_approval_identity_match_uses_cached_action_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = ActionRun(
        correlation_id="resource-bound-approval",
        action_type="ops.restart-service",
        resource_id="resource:approval",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        idempotency_key="resource-bound-approval:action",
        params={"large": list(range(10_000))},
    )
    run_identity = run.to_dict()
    run_identity["action_run_identity"] = run.action_run_identity()
    run_identity["_action_run_identity_verified"] = True
    approval = {
        "producer_principal": "Var",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "idempotency_key": "approval:resource-bound-approval",
        "approvers": ["operator"],
        "action_run_identity": run.action_run_identity(),
        "action_id": run.action_id,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "action_idempotency_key": run.idempotency_key,
        "rollback_contract": run.rollback_contract,
        "state": "approved",
    }

    def fail_json_dumps(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("approval match recanonicalized ActionRun identity")

    monkeypatch.setattr(identity_module.json, "dumps", fail_json_dumps)
    for _ in range(100):
        assert approval_matches_action_run(approval, run_identity)


async def test_vidar_rollback_locks_are_removed_after_terminal_rollbacks() -> None:
    async def executor(_command: dict[str, Any]) -> str:
        return "rollback:resource-bound"

    vidar = Vidar(
        executors={"state_forward_only": executor},
        allow_process_local_rollback=True,
    )

    for index in range(200):
        await vidar.rollback(_failed_action_run(f"resource-bound-lock-{index}"))

    assert len(vidar._rollback_locks) == 0  # noqa: SLF001


async def test_vidar_process_local_terminal_fences_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Vidar, "_MAX_RECORDS", 8)

    async def executor(_command: dict[str, Any]) -> str:
        return "rollback:resource-bound"

    vidar = Vidar(
        executors={"state_forward_only": executor},
        allow_process_local_rollback=True,
    )

    for index in range(32):
        await vidar.rollback(_failed_action_run(f"resource-bound-fence-{index}"))

    assert len(vidar._process_local_terminal_fences) == 8  # noqa: SLF001


async def test_vidar_duplicate_terminal_replay_skips_rollback_command_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def executor(_command: dict[str, Any]) -> str:
        return "rollback:resource-bound"

    deepcopy_calls = 0
    original_deepcopy = vidar_module.deepcopy

    def counting_deepcopy(value: Any) -> Any:
        nonlocal deepcopy_calls
        deepcopy_calls += 1
        return original_deepcopy(value)

    monkeypatch.setattr(vidar_module, "deepcopy", counting_deepcopy)
    vidar = Vidar(
        executors={"state_forward_only": executor},
        allow_process_local_rollback=True,
    )
    action_run = _failed_action_run("resource-bound-duplicate", payload_size=10_000)

    await vidar.rollback(action_run)
    deepcopy_calls = 0
    for _ in range(100):
        assert await vidar.rollback(action_run) is None

    assert deepcopy_calls == 0
    assert vidar.behavior_snapshot()["rollback:publication_unavailable"] == 101


async def test_forseti_recovery_pages_more_than_resource_bound_completions() -> None:
    store = InMemoryStateStore()
    forseti = Forseti(state_store=store, test_context_clock=lambda: _NOW)

    for index in range(_MAX_RESOURCES + 1):
        correlation_id = f"resource-bound-completed-{index}"
        await store.write_state(
            f"pantheon/forseti/arbitration-completed|{correlation_id}",
            {
                "kind": "arbitration_completed",
                "correlation_id": correlation_id,
                "outcome": "completed",
                "recorded_at": _NOW.isoformat(),
            },
        )

    restored = await rehydrate_arbitration_state(forseti)

    assert restored == _MAX_RESOURCES + 1
    assert len(forseti.arbitrations) == _MAX_RESOURCES


async def test_forseti_rehydrates_pending_candidates_with_one_timeout_scheduler() -> None:
    store = InMemoryStateStore()
    forseti = Forseti(
        state_store=store,
        test_context_clock=lambda: _NOW,
        cross_vertical_timeout_seconds=60.0,
    )
    deadline = _NOW + timedelta(minutes=5)

    for index in range(_MAX_RESOURCES + 1):
        correlation_id = f"resource-bound-pending-{index}"
        await store.write_state(
            f"pantheon/forseti/cross-vertical-pending|{correlation_id}",
            {
                "kind": "cross_vertical_pending",
                "status": "pending",
                "correlation_id": correlation_id,
                "resource_id": f"resource:{index}",
                "observed_at": _NOW.isoformat(),
                "deadline_at": deadline.isoformat(),
                "candidates": [_candidate("object.cost-anomaly", correlation_id)],
            },
        )

    restored = await rehydrate_arbitration_state(forseti)

    assert restored == _MAX_RESOURCES + 1
    assert len(forseti._cross_vertical_timeout_tasks) == 1  # noqa: SLF001
    assert len(forseti._cross_vertical_timeout_deadlines) == _MAX_RESOURCES  # noqa: SLF001
    for task in list(forseti._cross_vertical_timeout_tasks.values()):  # noqa: SLF001
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
