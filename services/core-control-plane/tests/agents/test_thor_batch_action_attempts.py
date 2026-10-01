"""Thor multi-target ActionAttempt batch semantics regressions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework import thor_batch
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RAW_TOPIC = "fdai.events.batch-test"


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"test.batch": False},
        rollback_by_id={"test.batch": "state_forward_only"},
    )


def _safeguards(idempotency_key: str) -> dict[str, object]:
    return {
        "stop_condition": "stop when postcondition is false",
        "tested_rollback_contract": "state_forward_only:test-receipt",
        "blast_radius_limit": {"scope": "resource", "max_targets": 2},
        "dry_run_receipt": "sha256:" + "1" * 64,
        "logical_target_lock": "lock:target-set:test",
        "stable_idempotency_key": idempotency_key,
        "two_phase_audit_intent": "audit-intent:test",
    }


def _batch_verdict(**overrides: Any) -> dict[str, Any]:
    idempotency_key = str(overrides.get("idempotency_key") or "batch-verdict-key")
    payload: dict[str, Any] = {
        "producer_principal": "Forseti",
        "correlation_id": "batch-correlation",
        "idempotency_key": idempotency_key,
        "action_type": "test.batch",
        "risk_verdict": "auto",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
        "targets": ["resource-a", "resource-b"],
        "params": {"replicas": 2},
        "safeguards": _safeguards(idempotency_key),
        "initiator_principal": "operator@example.com",
    }
    payload.update(overrides)
    return payload


async def _run_until(
    runtime: PantheonRuntime,
    predicate: Any,
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def test_batch_rollup_rejected_attempt_is_not_reported_as_rolled_back() -> None:
    rollup = ActionRun(
        correlation_id="batch-refused",
        action_type="test.batch",
        resource_id="target-set:test",
        state=ActionRunState.VERDICTED,
        verdict="auto",
        batch_role="rollup",
    )
    succeeded = ActionRun(
        correlation_id="attempt-ok",
        action_type="test.batch",
        resource_id="resource-a",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        batch_role="attempt",
        rollup_correlation_id=rollup.correlation_id,
    )
    rejected = ActionRun(
        correlation_id="attempt-rejected",
        action_type="test.batch",
        resource_id="resource-b",
        state=ActionRunState.REJECTED,
        verdict="auto",
        batch_role="attempt",
        rollup_correlation_id=rollup.correlation_id,
    )

    thor_batch.refresh_rollup(rollup, (succeeded, rejected))

    assert rollup.state is ActionRunState.ROLLBACK_FAILED
    assert rollup.outcome == "batch_refused_attempt"
    assert rollup.batch_rollup is not None
    assert rollup.batch_rollup["succeeded"] == 1
    assert rollup.batch_rollup["rejected"] == 1
    assert rollup.batch_rollup["deny_dropped"] == 0
    assert rollup.batch_rollup["rolled_back"] == 0
    assert rollup.batch_rollup["terminal_state_rule"] == "mixed_success_and_refused_attempt"


def _approval_for_run(run: Any) -> dict[str, Any]:
    return {
        "kind": "action",
        "state": "approved",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"approval:{run.idempotency_key}",
        "action_id": run.action_id,
        "action_type": run.action_type,
        "action_run_identity": run.action_run_identity(),
        "action_idempotency_key": run.idempotency_key,
        "resource_id": run.resource_id,
        "rollback_contract": run.rollback_contract,
        "approvers": ["approver@example.com"],
        "target_set_digest": run.target_set_digest,
    }


def test_multi_target_batch_attempts_roll_back_only_failed_target_and_audit_rollup() -> None:
    bus = _bus()
    saga = Saga()
    saga.bind_bus(bus)
    executed: list[str] = []
    rolled_back: list[str] = []

    async def executor(command: dict[str, object]) -> bool:
        run = command["run"]
        resource_id = str(run.resource_id)
        executed.append(resource_id)
        return resource_id != "resource-b"

    async def rollback(command: dict[str, object]) -> str:
        rolled_back.append(str(command["resource_id"]))
        return "rollback:resource-b"

    thor = Thor(bus=bus, executor=executor, action_semantics_catalog=_semantics())
    vidar = Vidar(
        bus=bus,
        executors={"state_forward_only": rollback},
        state_store=InMemoryStateStore(),
    )
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Saga", saga.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    rollup = asyncio.run(thor.dispatch_verdict(_batch_verdict()))

    attempts = [
        run
        for run in thor.action_runs.values()
        if run.rollup_correlation_id == rollup.correlation_id
    ]
    assert {attempt.resource_id for attempt in attempts} == {"resource-a", "resource-b"}
    assert len({attempt.attempt_id for attempt in attempts}) == 2
    assert executed == ["resource-a", "resource-b"]
    assert rolled_back == ["resource-b"]
    failed_attempt = next(attempt for attempt in attempts if attempt.resource_id == "resource-b")
    assert failed_attempt.state is ActionRunState.ROLLED_BACK
    sibling = next(attempt for attempt in attempts if attempt.resource_id == "resource-a")
    assert sibling.state is ActionRunState.EFFECT_PENDING

    asyncio.run(
        thor.on_typed_message(
            "object.recovery-effect-observation",
            {
                "producer_principal": "Heimdall",
                "schema_version": "1.0.0",
                "event_type": "action.execution.effect_verified.v1",
                "correlation_id": sibling.correlation_id,
                "idempotency_key": "effect-resource-a",
                "resource_id": sibling.resource_id,
                "action_id": sibling.action_id,
                "action_type": sibling.action_type,
                "action_idempotency_key": sibling.idempotency_key,
                "params": sibling.params,
                "effect_verification_ref": "sha256:" + "b" * 64,
                "execution_closure_ref": "sha256:" + "c" * 64,
                "observed_at": "2026-10-01T00:00:00+00:00",
            },
        )
    )

    assert rollup.state is ActionRunState.ROLLED_BACK
    assert rollup.outcome == "batch_mixed_outcome"
    assert rollup.batch_rollup is not None
    assert rollup.batch_rollup["succeeded"] == 1
    assert rollup.batch_rollup["rolled_back"] == 1
    assert rollup.batch_rollup["terminal_state_rule"] == "mixed_success_and_target_rollback"
    assert len(rollup.batch_rollup["rolled_back_target_digests"]) == 1

    action_run_payloads = [message.payload for message in bus.messages_on("object.action-run")]
    rollup_payloads = [
        payload
        for payload in action_run_payloads
        if payload["correlation_id"] == rollup.correlation_id
        and payload.get("batch_role") == "rollup"
    ]
    assert rollup_payloads[-1]["batch_rollup"]["rolled_back"] == 1
    attempt_payloads = [payload for payload in action_run_payloads if payload.get("attempt_id")]
    assert {payload["resource_id"] for payload in attempt_payloads} == {"resource-a", "resource-b"}

    audit_payloads = [message.payload for message in bus.messages_on("object.audit-entry")]
    attempt_audits = [
        payload
        for payload in audit_payloads
        if payload.get("audited_topic") == "object.action-run" and payload.get("attempt_id")
    ]
    rollup_audits = [
        payload
        for payload in audit_payloads
        if payload.get("audited_topic") == "object.action-run"
        and payload.get("batch_role") == "rollup"
    ]
    assert {payload["resource_id"] for payload in attempt_audits} == {"resource-a", "resource-b"}
    assert rollup_audits[-1]["batch_rollup"]["terminal"] is True


def test_multi_target_batch_over_limit_is_held_visibly_without_attempts() -> None:
    bus = _bus()
    thor = Thor(bus=bus, action_semantics_catalog=_semantics())

    run = asyncio.run(
        thor.dispatch_verdict(
            _batch_verdict(
                correlation_id="batch-over-limit",
                idempotency_key="batch-over-limit-key",
                targets=["resource-a", "resource-b", "resource-c"],
            )
        )
    )

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "batch_target_set_over_limit"
    assert run.shadow_mode is True
    assert not [candidate for candidate in thor.action_runs.values() if candidate.attempt_id]


def test_multi_target_batch_rehydrate_does_not_duplicate_attempt_executor_calls() -> None:
    store = InMemoryStateStore()
    started_at = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    first_calls: list[str] = []
    replay_calls: list[str] = []

    async def first_executor(command: dict[str, object]) -> bool:
        run = command["run"]
        first_calls.append(str(run.resource_id))
        return str(run.resource_id) != "resource-b"

    async def replay_executor(command: dict[str, object]) -> bool:
        run = command["run"]
        replay_calls.append(str(run.resource_id))
        return True

    first = Thor(
        bus=_bus(),
        executor=first_executor,
        state_store=StateStoreActionRunStore(
            store,
            owner_id="first-owner",
            claim_lease_seconds=1,
            clock=lambda: started_at,
        ),
        action_semantics_catalog=_semantics(),
        clock=lambda: started_at,
    )
    asyncio.run(first.dispatch_verdict(_batch_verdict(correlation_id="batch-restart")))
    assert first_calls == ["resource-a", "resource-b"]

    replayed = Thor(
        bus=_bus(),
        executor=replay_executor,
        state_store=StateStoreActionRunStore(
            store,
            owner_id="second-owner",
            claim_lease_seconds=1,
            clock=lambda: started_at + timedelta(seconds=2),
        ),
        action_semantics_catalog=_semantics(),
        clock=lambda: started_at + timedelta(seconds=2),
    )
    restored = asyncio.run(replayed.rehydrate())

    assert restored >= 1
    assert replay_calls == []


def test_hil_batch_rehydrate_approval_uses_durable_target_set_on_async_bus() -> None:
    store = InMemoryStateStore()
    first_provider = LocalEventBus()
    first_runtime = PantheonRuntime.build(
        provider=first_provider,
        raw_event_topic=_RAW_TOPIC,
        thor_state_store=StateStoreActionRunStore(store),
        rollback_executors={"state_forward_only": lambda _command: asyncio.sleep(0, "rollback")},
        vidar_state_store=InMemoryStateStore(),
    )
    first_thor = first_runtime.agents["Thor"]
    assert isinstance(first_thor, Thor)
    first_thor.set_action_semantics(_semantics())
    first_thor.set_shadow(False)

    async def _park_hil_rollup() -> None:
        await first_runtime.bridge.publish(
            "Forseti",
            "object.verdict",
            _batch_verdict(
                correlation_id="hil-batch",
                idempotency_key="hil-batch-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
            ),
        )
        await _run_until(
            first_runtime,
            lambda: (
                "hil-batch" in first_thor.action_runs
                and first_thor.action_runs["hil-batch"].state is ActionRunState.HIL_PENDING
            ),
        )

    asyncio.run(_park_hil_rollup())
    assert first_thor.action_runs["hil-batch"].target_set == ("resource-a", "resource-b")

    second_provider = LocalEventBus()
    executed: list[str] = []
    rolled_back: list[str] = []

    async def executor(command: dict[str, object]) -> bool:
        run = command["run"]
        executed.append(str(run.resource_id))
        return str(run.resource_id) != "resource-b"

    async def rollback(command: dict[str, object]) -> str:
        rolled_back.append(str(command["resource_id"]))
        return "rollback:resource-b"

    second_runtime = PantheonRuntime.build(
        provider=second_provider,
        raw_event_topic=_RAW_TOPIC,
        thor_executor=executor,
        thor_state_store=StateStoreActionRunStore(store),
        rollback_executors={"state_forward_only": rollback},
        vidar_state_store=InMemoryStateStore(),
    )
    second_thor = second_runtime.agents["Thor"]
    assert isinstance(second_thor, Thor)
    second_thor.set_action_semantics(_semantics())
    second_thor.set_shadow(False)

    async def _approve_after_restart() -> None:
        restored = await second_thor.rehydrate()
        assert restored == 1
        rollup = second_thor.action_runs["hil-batch"]
        assert rollup.target_set == ("resource-a", "resource-b")
        await second_runtime.bridge.publish("Var", "object.approval", _approval_for_run(rollup))
        await _run_until(
            second_runtime,
            lambda: (
                len(executed) == 2
                and "resource-b" in rolled_back
                and any(
                    run.rollup_correlation_id == "hil-batch"
                    and run.resource_id == "resource-b"
                    and run.state is ActionRunState.ROLLED_BACK
                    for run in second_thor.action_runs.values()
                )
            ),
        )
        succeeded = next(
            run
            for run in second_thor.action_runs.values()
            if run.rollup_correlation_id == "hil-batch" and run.resource_id == "resource-a"
        )
        await second_runtime.bridge.publish(
            "Heimdall",
            "object.recovery-effect-observation",
            {
                "schema_version": "1.0.0",
                "event_type": "action.execution.effect_verified.v1",
                "correlation_id": succeeded.correlation_id,
                "idempotency_key": "hil-batch-effect-resource-a",
                "resource_id": succeeded.resource_id,
                "action_id": succeeded.action_id,
                "action_type": succeeded.action_type,
                "action_idempotency_key": succeeded.idempotency_key,
                "params": succeeded.params,
                "effect_verification_ref": "sha256:" + "d" * 64,
                "execution_closure_ref": "sha256:" + "e" * 64,
                "observed_at": "2026-10-01T00:00:00+00:00",
            },
        )
        await _run_until(
            second_runtime,
            lambda: (
                second_thor.action_runs["hil-batch"].state is ActionRunState.ROLLED_BACK
                and any(
                    payload.get("audited_topic") == "object.action-run"
                    and payload.get("batch_role") == "rollup"
                    and payload.get("batch_rollup", {}).get("terminal") is True
                    for payload in _payloads(second_provider, "object.audit-entry")
                )
            ),
        )

    asyncio.run(_approve_after_restart())

    assert executed == ["resource-a", "resource-b"]
    assert rolled_back == ["resource-b"]
    audit_payloads = _payloads(second_provider, "object.audit-entry")
    attempt_audits = [
        payload
        for payload in audit_payloads
        if payload.get("audited_topic") == "object.action-run" and payload.get("attempt_id")
    ]
    rollup_audits = [
        payload
        for payload in audit_payloads
        if payload.get("audited_topic") == "object.action-run"
        and payload.get("batch_role") == "rollup"
    ]
    assert {payload["resource_id"] for payload in attempt_audits} == {"resource-a", "resource-b"}
    assert rollup_audits[-1]["batch_rollup"]["terminal"] is True


def test_batch_rollup_rehydrate_holds_target_set_digest_mismatch_visibly() -> None:
    store = InMemoryStateStore()
    thor = Thor(
        bus=_bus(),
        state_store=StateStoreActionRunStore(store),
        action_semantics_catalog=_semantics(),
    )
    asyncio.run(
        thor.dispatch_verdict(
            _batch_verdict(
                correlation_id="mismatch-batch",
                idempotency_key="mismatch-batch-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
            )
        )
    )

    key = "thor:run|mismatch-batch"
    stored = asyncio.run(store.read_state(key))
    assert stored is not None
    tampered = dict(stored)
    tampered["target_set"] = ["resource-a", "resource-c"]
    asyncio.run(store.write_state(key, tampered))

    replayed = Thor(
        bus=_bus(),
        state_store=StateStoreActionRunStore(store),
        action_semantics_catalog=_semantics(),
    )
    restored = asyncio.run(replayed.rehydrate())

    assert restored == 1
    run = replayed.action_runs["mismatch-batch"]
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "batch_target_set_digest_mismatch"
