"""Dispatch phase timestamps are observations, never effect or authority claims."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.thor_dispatch_start import (
    DISPATCH_START_PREFIX,
    dispatch_start_key,
)
from fdai.agents._framework.thor_execution import execute, invoke_executor
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.core.executor.safeguards import resource_lock_key
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_thor_durable import _verdict

NOW = datetime(2026, 10, 19, tzinfo=UTC)


class _RecordingStore(StateStoreActionRunStore):
    def __init__(self) -> None:
        super().__init__(store=InMemoryStateStore())
        self.started_at: datetime | None = None

    async def record_dispatch_start(
        self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
    ) -> None:
        assert run.state is ActionRunState.EXECUTING
        self.started_at = started_at


def _run() -> ActionRun:
    return ActionRun(
        correlation_id="dispatch-test",
        action_type="example.action",
        resource_id="resource-1",
        state=ActionRunState.EXECUTING,
        verdict="auto",
    )


async def test_dispatch_start_is_persisted_before_executor_without_second_run_save() -> None:
    store = _RecordingStore()
    calls: list[str] = []

    async def executor(payload: dict[str, Any]) -> bool:
        assert payload["run"].correlation_id == "dispatch-test"
        assert store.started_at == NOW
        calls.append("executor")
        return True

    host = Thor(executor=executor, state_store=store, clock=lambda: NOW)
    assert await invoke_executor(host, _run())
    assert calls == ["executor"]
    assert await store.load_active() == []


async def test_dispatch_start_is_captured_after_resource_lock_admission() -> None:
    store = _RecordingStore()
    clock = [NOW]
    events: list[str] = []

    class Lock:
        @asynccontextmanager
        async def acquire(self, resource_id: str) -> AsyncIterator[None]:
            assert resource_id
            events.append("locked")
            clock[0] = NOW + timedelta(seconds=30)
            try:
                yield
            finally:
                events.append("released")

    async def executor(payload: dict[str, Any]) -> bool:
        assert payload["run"].resource_id == "resource-1"
        assert store.started_at == NOW + timedelta(seconds=30)
        events.append("executor")
        return True

    host = Thor(
        executor=executor,
        state_store=store,
        clock=lambda: clock[0],
        execution_resource_lock=Lock(),
    )
    assert await invoke_executor(host, _run())
    assert events == ["locked", "executor", "released"]


async def test_default_durable_store_retains_observation_not_a_second_run_save() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = _run()

    async def executor(payload: dict[str, Any]) -> bool:
        assert payload["run"] is run
        recorded = await state.read_state(dispatch_start_key(run.correlation_id))
        assert recorded is not None
        assert recorded["dispatch_started_at"] == NOW.isoformat()
        assert recorded["action_run_identity"] == run.action_run_identity()
        assert recorded["resource_id"] == run.resource_id
        assert recorded["resource_lock_ref"] is None
        assert recorded["effect_verified"] is False
        assert recorded["history_complete"] is False
        return True

    assert await invoke_executor(Thor(executor=executor, state_store=store, clock=lambda: NOW), run)
    assert await store.load_active() == []


async def test_first_dispatch_time_is_immutable_on_a_same_identity_retry() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = _run()
    await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)
    first = await state.read_state(dispatch_start_key(run.correlation_id))
    await store.record_dispatch_start(
        run, started_at=NOW + timedelta(seconds=10), resource_lock_ref=None
    )
    assert await state.read_state(dispatch_start_key(run.correlation_id)) == first
    with pytest.raises(RuntimeError, match="causal"):
        await store.record_dispatch_start(
            run, started_at=NOW - timedelta(seconds=1), resource_lock_ref=None
        )


async def test_conflicting_execution_identity_cannot_reuse_a_dispatch_observation() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    await store.record_dispatch_start(_run(), started_at=NOW, resource_lock_ref=None)
    changed = _run()
    changed.params = {"changed": "request"}
    with pytest.raises(RuntimeError, match="conflicts"):
        await store.record_dispatch_start(changed, started_at=NOW, resource_lock_ref=None)


@pytest.mark.parametrize("mutation", ["shadow", "state", "clock"])
async def test_invalid_dispatch_observations_never_write(mutation: str) -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run, at = _run(), NOW
    if mutation == "shadow":
        run.shadow_mode = True
    elif mutation == "state":
        run.state = ActionRunState.PROPOSED
    else:
        at = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError):
        await store.record_dispatch_start(run, started_at=at, resource_lock_ref=None)
    rows, total = await state.read_state_page(DISPATCH_START_PREFIX, limit=10)
    assert rows == () and total == 0


async def test_shadow_execution_writes_no_dispatch_observation_or_executor_call() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = _run()
    run.state, run.shadow_mode = ActionRunState.VERDICTED, True

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("shadow run reached the privileged executor")

    await execute(Thor(executor=executor, state_store=store, clock=lambda: NOW), run)
    assert run.outcome == "shadow_success"
    rows, total = await state.read_state_page(DISPATCH_START_PREFIX, limit=10)
    assert rows == () and total == 0


@pytest.mark.parametrize("cancelled", [False, True])
async def test_recording_failure_prevents_executor_io_and_releases_lock(cancelled: bool) -> None:
    import asyncio

    events: list[str] = []

    class FailedStore(_RecordingStore):
        async def record_dispatch_start(
            self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
        ) -> None:
            if cancelled:
                raise asyncio.CancelledError
            raise RuntimeError("injected dispatch observation failure")

    class Lock:
        @asynccontextmanager
        async def acquire(self, key: str) -> AsyncIterator[None]:
            events.append("locked")
            try:
                yield
            finally:
                events.append("released")

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("failed observation reached privileged executor I/O")

    host = Thor(
        executor=executor,
        state_store=FailedStore(),
        execution_resource_lock=Lock(),
        clock=lambda: NOW,
    )
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await invoke_executor(host, _run())
    assert events == ["locked", "released"]


async def test_observation_wait_rechecks_development_authority_before_executor() -> None:
    store = _RecordingStore()
    events: list[str] = []

    class Host(Thor):
        def _revalidate_development_authority(self, run: ActionRun) -> None:
            if store.started_at is not None:
                raise ValueError("authority changed while recording")

    class Lock:
        @asynccontextmanager
        async def acquire(self, key: str) -> AsyncIterator[None]:
            try:
                yield
            finally:
                events.append("released")

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("expired authority reached the executor")

    host = Host(
        executor=executor, state_store=store, execution_resource_lock=Lock(), clock=lambda: NOW
    )
    with pytest.raises(ValueError, match="authority changed"):
        await invoke_executor(host, _run())
    assert events == ["released"]


async def test_retained_observation_type_corruption_cannot_become_a_valid_replay() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = _run()
    await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)
    key = dispatch_start_key(run.correlation_id)
    recorded = await state.read_state(key)
    assert recorded is not None
    await state.write_state(key, {**recorded, "effect_verified": 0})
    with pytest.raises(RuntimeError, match="conflicts"):
        await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)


@pytest.mark.parametrize("mutate_original", [False, True])
async def test_observer_cannot_change_the_approved_execution_payload(mutate_original: bool) -> None:
    run = _run()
    calls: list[str] = []

    class MutatingStore(_RecordingStore):
        async def record_dispatch_start(
            self, observed: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
        ) -> None:
            target = run if mutate_original else observed
            target.params["injected"] = "changed"

    async def executor(payload: dict[str, Any]) -> bool:
        assert payload["run"].params == {}
        calls.append("executor")
        return True

    host = Thor(executor=executor, state_store=MutatingStore(), clock=lambda: NOW)
    if mutate_original:
        with pytest.raises(RuntimeError, match="identity changed"):
            await invoke_executor(host, run)
        assert not calls
    else:
        assert await invoke_executor(host, run)
        assert calls == ["executor"] and run.params == {}


async def test_missing_retained_row_after_failed_atomic_create_is_not_success() -> None:
    class MissingState(InMemoryStateStore):
        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            return False

    store = StateStoreActionRunStore(store=MissingState())
    with pytest.raises(RuntimeError, match="unavailable"):
        await store.record_dispatch_start(_run(), started_at=NOW, resource_lock_ref=None)


async def test_missing_execution_identity_is_not_recorded() -> None:
    store = StateStoreActionRunStore(store=InMemoryStateStore())
    run = _run()
    run.correlation_id = ""
    with pytest.raises(ValueError, match="identity"):
        await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)


@pytest.mark.parametrize("timestamp", [0, "invalid", NOW.replace(tzinfo=None).isoformat()])
async def test_malformed_retained_timestamp_cannot_be_replayed(timestamp: object) -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = _run()
    await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)
    key = dispatch_start_key(run.correlation_id)
    retained = await state.read_state(key)
    assert retained is not None
    await state.write_state(key, {**retained, "dispatch_started_at": timestamp})
    with pytest.raises(RuntimeError, match="timestamp"):
        await store.record_dispatch_start(run, started_at=NOW, resource_lock_ref=None)


@pytest.mark.parametrize("mutation", ["authority", "state", "shadow"])
async def test_shadow_authority_change_during_recording_prevents_executor_io(
    mutation: str,
) -> None:
    shadow = False
    original = _run()

    class ChangedAuthorityStore(_RecordingStore):
        async def record_dispatch_start(
            self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
        ) -> None:
            nonlocal shadow
            await super().record_dispatch_start(
                run, started_at=started_at, resource_lock_ref=resource_lock_ref
            )
            if mutation == "authority":
                shadow = True
            elif mutation == "state":
                original.state = ActionRunState.FAILED
            else:
                original.shadow_mode = True

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("authority changed during observation but executor was invoked")

    host = Thor(
        executor=executor,
        state_store=ChangedAuthorityStore(),
        shadow_required=lambda: shadow,
        clock=lambda: NOW,
    )
    with pytest.raises(RuntimeError, match="authority"):
        await invoke_executor(host, original)


async def test_actual_verdict_dispatch_binds_durable_claim_lock_and_audit_receipt() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state, clock=lambda: NOW)
    verdict = _verdict()
    locked = False

    class Lock:
        @asynccontextmanager
        async def acquire(self, key: str) -> AsyncIterator[None]:
            nonlocal locked
            assert key == resource_lock_key(str(verdict["resource_id"]))
            locked = True
            try:
                yield
            finally:
                locked = False

    async def audit(run: ActionRun) -> str:
        assert not locked
        return "saga-audit-receipt"

    async def executor(payload: dict[str, Any]) -> bool:
        run = payload["run"]
        assert isinstance(run, ActionRun) and run.resource_id is not None
        assert locked
        assert await store.validate_resource_claim(run)
        recorded = await state.read_state(dispatch_start_key(run.correlation_id))
        assert recorded is not None
        assert recorded["resource_lock_ref"] == resource_lock_key(run.resource_id)
        assert recorded["execution_audit_receipt"] == "saga-audit-receipt"
        assert recorded["action_run_identity"] == run.action_run_identity()
        persisted = await state.read_state(f"{store.run_prefix}{run.correlation_id}")
        assert persisted is not None and persisted["state"] == "executing"
        assert "dispatch_started_at" not in persisted
        return True

    host = Thor(
        executor=executor,
        state_store=store,
        execution_resource_lock=Lock(),
        require_execution_resource_lock=True,
        require_execution_audit=True,
        execution_audit_recorder=audit,
        clock=lambda: NOW,
    )
    run = await host.dispatch_verdict(verdict)
    assert run.state is ActionRunState.EFFECT_PENDING
    assert run.outcome == "command_accepted_verification_pending"
    assert not locked


@pytest.mark.parametrize("prior,replacement", [(True, 1), (False, 0), (1, 1.0)])
@pytest.mark.parametrize("during_await", [False, True])
async def test_json_type_changes_cannot_reuse_cached_dispatch_identity(
    prior: object, replacement: object, during_await: bool
) -> None:
    original = _run()
    original.params = {"nested": {"value": prior}}
    original.action_run_identity()
    state = InMemoryStateStore()

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("changed JSON identity reached the executor")

    if during_await:

        class ChangedStore(_RecordingStore):
            async def record_dispatch_start(
                self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
            ) -> None:
                original.params["nested"]["value"] = replacement

        with pytest.raises(RuntimeError, match="identity changed"):
            await invoke_executor(
                Thor(executor=executor, state_store=ChangedStore(), clock=lambda: NOW), original
            )
    else:
        store = StateStoreActionRunStore(store=state)
        await store.record_dispatch_start(original, started_at=NOW, resource_lock_ref=None)
        original.params["nested"]["value"] = replacement
        with pytest.raises(RuntimeError, match="conflicts"):
            await store.record_dispatch_start(original, started_at=NOW, resource_lock_ref=None)
