from __future__ import annotations

import asyncio
import socket

from fdai_executor_service.health import RuntimeHealthServer


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _request(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def test_executor_health_distinguishes_liveness_from_readiness() -> None:
    ready = False
    server = RuntimeHealthServer(port=_available_port(), readiness=lambda: ready)
    await server.start()
    try:
        assert (await _request(server.port, "/live")).startswith(b"HTTP/1.1 200")
        assert (await _request(server.port, "/ready")).startswith(b"HTTP/1.1 503")
        ready = True
        assert (await _request(server.port, "/ready")).startswith(b"HTTP/1.1 200")
        assert (await _request(server.port, "/unknown")).startswith(b"HTTP/1.1 404")
        assert (await _request(server.port, "/" + "a" * 2100)).startswith(b"HTTP/1.1 404")
        await server.start()
    finally:
        await server.close()
        await server.close()


def test_health_server_rejects_invalid_port() -> None:
    import pytest

    with pytest.raises(ValueError, match="between 1 and 65535"):
        RuntimeHealthServer(port=0)


async def test_lifecycle_and_main_entrypoint(
    monkeypatch: object,
    tmp_path: object,
) -> None:
    import fcntl
    import signal
    from pathlib import Path

    import pytest
    from fdai_executor_service import cli as cli_mod
    from fdai_executor_service import lifecycle, main

    mp: pytest.MonkeyPatch = monkeypatch  # type: ignore[assignment]
    tp: Path = tmp_path  # type: ignore[assignment]

    registered: dict[object, tuple[object, tuple[object, ...]]] = {}
    loop = asyncio.get_running_loop()
    mp.setattr(
        loop,
        "add_signal_handler",
        lambda sig, fn, *args: registered.__setitem__(sig, (fn, args)),
    )
    stop_event = lifecycle.install_shutdown_signals()
    assert not stop_event.is_set()
    fn, args = registered[signal.SIGTERM]
    fn(*args)  # type: ignore[operator]
    assert stop_event.is_set()

    mp.delenv("FDAI_ISOLATED_EXECUTOR_LOCK_FILE", raising=False)
    with lifecycle.executor_process_lock():
        pass

    lock_file = tp / "locks" / "executor.lock"
    mp.setenv("FDAI_ISOLATED_EXECUTOR_LOCK_FILE", str(lock_file))
    with lifecycle.executor_process_lock():
        assert lock_file.exists()

    def raise_blocking(*_args: object) -> None:
        raise BlockingIOError("already locked")

    mp.setattr(fcntl, "flock", raise_blocking)
    with pytest.raises(RuntimeError, match="already active"), lifecycle.executor_process_lock():
        pass

    mp.delenv("FDAI_ISOLATED_EXECUTOR_LOCK_FILE", raising=False)
    mp.setattr(asyncio, "run", lambda coro: (coro.close(), 0)[1])
    assert lifecycle.run_main(lambda: asyncio.sleep(0, result=0)) == 0

    def raise_kb(coro: object) -> int:
        coro.close()  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    mp.setattr(asyncio, "run", raise_kb)
    assert lifecycle.run_main(lambda: asyncio.sleep(0, result=0)) == 0

    recorded: list[object] = []
    mp.setattr(main, "record_runtime_scope_receipt", recorded.append)
    mp.setattr(cli_mod, "main", lambda: 0)
    assert main.main() == 0
    assert recorded == [main.SERVICE]


async def test_runtime_outbox_consumer_and_supervisor_branches(
    monkeypatch: object,
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from uuid import UUID

    import pytest
    from fdai_executor_service import runtime as runtime_mod
    from fdai_executor_service.runtime import (
        IsolatedExecutorCommandConsumer,
        IsolatedExecutorSupervisor,
        MemoryExecutorReceiptOutbox,
        _receipt_matches_command,
    )
    from fdai_executor_service.service import ExecutorCommandConflictError
    from fdai_service_contracts.executor import (
        Action,
        ActionStopCondition,
        BlastRadius,
        BlastRadiusScope,
        EventEnvelope,
        ExecutionPath,
        ExecutorCommand,
        ExecutorEffectReceipt,
        ExecutorEffectReceiptStatus,
        ExecutorShadowReceipt,
        ExecutorShadowReceiptStatus,
        Mode,
        Operation,
        PublishReceipt,
        RollbackKind,
        RollbackRef,
        SafeguardBoundExecutorCommand,
        StopConditionKind,
        executor_command_id_from_action_payload,
    )
    from fdai_service_contracts.schema import ContractValidationError

    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    outbox = MemoryExecutorReceiptOutbox()
    rid = UUID(int=1)
    await outbox.commit_receipt(rid, "pk", {"a": 1}, command_id="c1", command_offset=1)
    await outbox.commit_receipt(rid, "pk", {"a": 1}, command_id="c1", command_offset=1)
    with pytest.raises(RuntimeError, match="different terminal receipt"):
        await outbox.commit_receipt(rid, "pk", {"a": 2}, command_id="c1", command_offset=1)
    claimed = await outbox.claim_receipts(limit=10)
    assert len(claimed) == 1
    await outbox.mark_receipt_published(rid)
    assert await outbox.claim_receipts(limit=10) == ()

    with pytest.raises(ValueError, match="settings MUST be valid"):
        IsolatedExecutorCommandConsumer(
            event_bus=object(),  # type: ignore[arg-type]
            service=object(),  # type: ignore[arg-type]
            command_topic="",
        )
    with pytest.raises(ValueError, match="topics MUST differ"):
        IsolatedExecutorCommandConsumer(
            event_bus=object(),  # type: ignore[arg-type]
            service=object(),  # type: ignore[arg-type]
            command_topic="same",
            receipt_topic="same",
        )
    with pytest.raises(ValueError, match="freshness MUST cover"):
        IsolatedExecutorCommandConsumer(
            event_bus=object(),  # type: ignore[arg-type]
            service=object(),  # type: ignore[arg-type]
            retry_seconds=5.0,
            outbox_readiness_freshness_seconds=1.0,
        )

    action = Action(
        schema_version="1.0.0",
        action_id=UUID(int=2),
        idempotency_key="rt-key-1",
        event_id=UUID(int=3),
        action_type="ops.start-vm",
        target_resource_ref="/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app",
        operation=Operation.ENABLE,
        params={"resource_group": "example", "vm_name": "vm-app"},
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=60)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.SHADOW,
        citing_rules=["rule.example"],
        created_at=now,
    )
    cmd = ExecutorCommand.from_action(
        command_id=UUID(int=4),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now,
        deadline_at=now + timedelta(minutes=5),
    )
    shadow_receipt = ExecutorShadowReceipt(
        receipt_id=UUID(int=5),
        command_id=cmd.command_id,
        action_id=cmd.action_id,
        idempotency_key=cmd.idempotency_key,
        attempt=cmd.attempt,
        action_payload_digest=cmd.action_payload_digest,
        requested_mode=cmd.requested_mode,
        status=ExecutorShadowReceiptStatus.SHADOWED,
        reason="ok",
        executor_instance_id="inst-1",
        received_at=now,
        completed_at=now,
    )

    class _Bus:
        def __init__(self) -> None:
            self.dlq: list[tuple[str, str]] = []
            self.published: list[tuple[str, str, object]] = []
            self.sub_calls = 0

        async def publish(self, topic: str, key: str, payload: object) -> PublishReceipt:
            self.published.append((topic, key, payload))
            return PublishReceipt(topic=topic, partition=0, offset=1)

        async def dead_letter(self, topic: str, _key: str, _payload: object, reason: str) -> None:
            self.dlq.append((topic, reason))

        def subscribe(self, _topic: str, _group: str) -> AsyncIterator[EventEnvelope]:
            async def _gen() -> AsyncIterator[EventEnvelope]:
                self.sub_calls += 1
                if self.sub_calls == 1:
                    yield EventEnvelope(
                        topic="cmd",
                        key=cmd.partition_key,
                        payload=cmd.model_dump(mode="json"),
                        offset=10,
                    )
                    return
                if self.sub_calls == 2:
                    raise RuntimeError("transient broker error")
                await asyncio.Event().wait()

            return _gen()

    class _Lock:
        @asynccontextmanager
        async def acquire(self, _key: str) -> AsyncIterator[None]:
            yield

    class _Svc:
        def __init__(self) -> None:
            self.err: Exception | None = None

        async def handle(self, _c: object) -> ExecutorShadowReceipt:
            if self.err is not None:
                raise self.err
            return shadow_receipt

    bus = _Bus()
    svc = _Svc()
    mem_outbox = MemoryExecutorReceiptOutbox()
    consumer = IsolatedExecutorCommandConsumer(
        event_bus=bus,  # type: ignore[arg-type]
        service=svc,
        retry_seconds=0.001,
        receipt_outbox=mem_outbox,
        command_lock=_Lock(),
    )

    # Invalid command payload -> dead-letter
    assert (
        await consumer.handle_envelope(
            EventEnvelope(topic="cmd", key="k", payload={"bad": 1}, offset=1)
        )
        is None
    )
    # Partition key mismatch -> dead-letter
    assert (
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd", key="wrong-key", payload=cmd.model_dump(mode="json"), offset=2
            )
        )
        is None
    )

    # SafeguardBoundExecutorCommand legacy_id and invalid command_id
    bound_enf = SafeguardBoundExecutorCommand.from_action(
        command_id=UUID(int=40),
        action=action.model_copy(update={"mode": Mode.ENFORCE}),
        execution_path=ExecutionPath.DIRECT_API,
        safeguard_proof_bundle_digest="sha256:" + "a" * 64,
        source_revision="commit:" + "b" * 40,
        attempt=1,
        issued_at=now,
        deadline_at=now + timedelta(minutes=5),
    )
    assert (
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd",
                key=bound_enf.partition_key,
                payload=bound_enf.model_dump(mode="json"),
                offset=3,
            )
        )
        is None
    )
    legacy_id = executor_command_id_from_action_payload(
        action_payload=bound_enf.action_payload,
        idempotency_key=bound_enf.idempotency_key,
    )
    legacy_bound_enf = bound_enf.model_copy(update={"command_id": legacy_id})
    assert (
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd",
                key=legacy_bound_enf.partition_key,
                payload=legacy_bound_enf.model_dump(mode="json"),
                offset=4,
            )
        )
        is None
    )

    # Service exception branches
    class FakeContractValidationError(ValueError):
        pass

    FakeContractValidationError.__name__ = "ContractValidationError"

    for exc in (
        ContractValidationError("executor-command", []),
        FakeContractValidationError("bad"),
        ExecutorCommandConflictError("conflict"),
    ):
        svc.err = exc
        assert (
            await consumer.handle_envelope(
                EventEnvelope(
                    topic="cmd",
                    key=cmd.partition_key,
                    payload=cmd.model_dump(mode="json"),
                    offset=5,
                )
            )
            is None
        )

    svc.err = ValueError("other value error")
    with pytest.raises(ValueError, match="other value error"):
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd",
                key=cmd.partition_key,
                payload=cmd.model_dump(mode="json"),
                offset=6,
            )
        )
    svc.err = None

    # Normal commit + replay from committed outbox + malformed/mismatched committed receipt
    r1 = await consumer.handle_envelope(
        EventEnvelope(
            topic="cmd",
            key=cmd.partition_key,
            payload=cmd.model_dump(mode="json"),
            offset=7,
        )
    )
    assert r1 == shadow_receipt
    r2 = await consumer.handle_envelope(
        EventEnvelope(
            topic="cmd",
            key=cmd.partition_key,
            payload=cmd.model_dump(mode="json"),
            offset=8,
        )
    )
    assert r2 == shadow_receipt
    assert await consumer._drain_once() == 1

    mem_outbox._committed_by_command[str(cmd.command_id)] = {
        **shadow_receipt.model_dump(mode="json"),
        "attempt": 99,
    }
    assert (
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd",
                key=cmd.partition_key,
                payload=cmd.model_dump(mode="json"),
                offset=9,
            )
        )
        is None
    )
    mem_outbox._committed_by_command[str(cmd.command_id)] = {"malformed": True}
    with pytest.raises(RuntimeError, match="malformed"):
        await consumer.handle_envelope(
            EventEnvelope(
                topic="cmd",
                key=cmd.partition_key,
                payload=cmd.model_dump(mode="json"),
                offset=9,
            )
        )
    mem_outbox._committed_by_command.clear()

    # Run loop with subscription, retry, and drain_outbox
    task = asyncio.create_task(consumer.run())
    try:
        async with asyncio.timeout(2.0):
            while bus.sub_calls < 3:
                await asyncio.sleep(0.002)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    # _receipt_matches_command with ExecutorEffectReceipt and non-DIRECT_API legacy command
    eff_rec = ExecutorEffectReceipt(
        receipt_id=UUID(int=60),
        command_id=cmd.command_id,
        action_id=cmd.action_id,
        idempotency_key=cmd.idempotency_key,
        attempt=cmd.attempt,
        action_payload_digest=cmd.action_payload_digest,
        requested_mode=cmd.requested_mode,
        status=ExecutorEffectReceiptStatus.REJECTED_INVARIANT,
        reason="r",
        executor_instance_id="inst-1",
        received_at=now,
        completed_at=now,
        effect_applied=False,
        audit_ref="action:1",
    )
    pr_cmd = cmd.model_copy(update={"execution_path": ExecutionPath.PR_NATIVE})
    assert _receipt_matches_command(pr_cmd, eff_rec) is False

    # Supervisor tests
    mp: pytest.MonkeyPatch = monkeypatch  # type: ignore[assignment]

    class _DummyHealthServer:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

    mp.setattr(runtime_mod, "RuntimeHealthServer", _DummyHealthServer)

    with pytest.raises(ValueError, match="between 1 and 65535"):
        IsolatedExecutorSupervisor(consumer=consumer, health_port=0)

    class _IdleLoop:
        async def run(self) -> None:
            await asyncio.Event().wait()

    sup = IsolatedExecutorSupervisor(
        consumer=_IdleLoop(),
        health_port=8080,
        startup_checks=(lambda: asyncio.sleep(0),),
        readiness_checks=(lambda: True,),
        shutdown_callbacks=(lambda: asyncio.sleep(0),),
    )
    assert sup.ready is False
    stop = asyncio.Event()
    sup_task = asyncio.create_task(sup.run(stop=stop))
    try:
        async with asyncio.timeout(2.0):
            while not sup.ready:
                await asyncio.sleep(0.002)
        stop.set()
        assert await sup_task == 0
    finally:
        if not sup_task.done():
            sup_task.cancel()
            await asyncio.gather(sup_task, return_exceptions=True)

    def bad_ready() -> bool:
        raise RuntimeError("probe boom")

    sup_bad_probe = IsolatedExecutorSupervisor(
        consumer=_IdleLoop(),
        health_port=8080,
        readiness_checks=(bad_ready,),
    )
    sup_bad_probe._ready = True
    sup_bad_probe._consumer_task = asyncio.create_task(asyncio.sleep(10))
    assert sup_bad_probe.ready is False
    sup_bad_probe._consumer_task.cancel()
    await asyncio.gather(sup_bad_probe._consumer_task, return_exceptions=True)

    class _ExitingLoop:
        async def run(self) -> None:
            return None

    async def failing_shutdown() -> None:
        raise RuntimeError("shutdown boom")

    sup_exit = IsolatedExecutorSupervisor(
        consumer=_ExitingLoop(),
        health_port=8080,
        shutdown_callbacks=(failing_shutdown,),
    )
    with pytest.raises(RuntimeError, match="runtime failed"):
        await sup_exit.run(stop=asyncio.Event())

    stop2 = asyncio.Event()
    stop2.set()
    sup_shut_fail = IsolatedExecutorSupervisor(
        consumer=_IdleLoop(),
        health_port=8080,
        shutdown_callbacks=(failing_shutdown,),
    )
    with pytest.raises(RuntimeError, match="runtime failed"):
        await sup_shut_fail.run(stop=stop2)
