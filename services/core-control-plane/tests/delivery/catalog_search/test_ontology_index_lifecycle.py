"""Local lifecycle mechanics; injected seals are not live agent audit evidence."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.catalog_search.ontology_index_lifecycle import (
    IndexGeneration,
    IndexScope,
    IndexTransition,
    OntologyIndexLifecycle,
)
from fdai.delivery.catalog_search.ontology_index_retention import reclaim_retired_index
from fdai.delivery.catalog_search.ontology_snapshot_store import _digest
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

NOW = datetime(2026, 9, 21, tzinfo=UTC)
SEAL = content_digest("synthetic-independent-admission")


def _scope(principal: str = "example-reader") -> IndexScope:
    return IndexScope(
        principal_scope_digest=content_digest(principal),
        role=CeilingRole.READER,
        purpose="operations-review",
    )


def _generation(number: int = 1) -> IndexGeneration:
    return IndexGeneration(
        scope=_scope(),
        manifest_digest=content_digest("manifest"),
        ontology_release_digest=content_digest("release"),
        source_generation=f"source-{number}",
        source_projection_digest=content_digest(("projection", number)),
        snapshot_digest=content_digest(("snapshot", number)),
        vector_digest=content_digest(("vectors", number)),
        generation_digest=content_digest(("generation", number)),
        validation_receipt_digest=content_digest(("validation", number)),
        embedding_space_id="example-space",
        embedding_model_version="example-model-v1",
        embedding_dimension=1,
    )


def _command(**changes: Any) -> IndexTransition:
    return IndexTransition.model_validate(
        {
            "command_id": "example-command",
            "scope": _scope(),
            "operation": "activate",
            "expected_revision": 0,
            "expected_active_digest": None,
            "target": _generation(),
            "requested_at": NOW,
            "expires_at": NOW + timedelta(seconds=30),
            **changes,
        }
    )


async def test_lifecycle_replays_across_restart_and_isolates_rule_and_principal_state() -> None:
    state = InMemoryStateStore()
    await state.write_state("catalog-search:active", {"generation": "rule-generation"})
    admit = AsyncMock(return_value=SEAL)
    lifecycle = OntologyIndexLifecycle(store=state, admit=admit, clock=lambda: NOW)
    command = _command()
    first = await lifecycle.apply(command)
    restarted = OntologyIndexLifecycle(store=state, admit=admit, clock=lambda: NOW)
    assert await restarted.apply(command) == first
    assert admit.await_count == 1
    assert (await restarted.read(_scope())).active == _generation()
    assert (await restarted.read(_scope("different-reader"))).active is None
    assert await state.read_state("catalog-search:active") == {"generation": "rule-generation"}
    with pytest.raises(ValueError, match="reused"):
        await restarted.apply(_command(target=_generation(2)))


@pytest.mark.parametrize("kind", ["missing", "expired", "expires_during", "stale", "race"])
async def test_failed_admission_or_revision_fence_preserves_previous_pointer(kind: str) -> None:
    state = InMemoryStateStore()
    now = NOW
    admit = AsyncMock(return_value=SEAL)
    lifecycle = OntologyIndexLifecycle(store=state, admit=admit, clock=lambda: now)
    await lifecycle.apply(_command())
    command = _command(
        command_id="next-command",
        expected_revision=1,
        expected_active_digest=_generation().digest,
        target=_generation(2),
    )
    if kind == "missing":
        admit.return_value = None
    elif kind == "expired":
        now += timedelta(seconds=31)
    elif kind == "expires_during":

        async def expire(_command: IndexTransition) -> str:
            nonlocal now
            now += timedelta(seconds=31)
            return SEAL

        admit.side_effect = expire
    elif kind == "stale":
        command = command.model_copy(update={"expected_revision": 0})
    elif kind == "race":
        command = command.model_copy(update={"expected_active_digest": content_digest("other")})
    with pytest.raises(ValueError):
        await lifecycle.apply(command)
    assert (await lifecycle.read(_scope())).active == _generation()
    assert (await lifecycle.read(_scope())).revision == 1


async def test_concurrent_commands_have_one_winner_and_exact_retry() -> None:
    state = InMemoryStateStore()
    arrived = 0
    all_arrived = asyncio.Event()

    async def admit(_command: IndexTransition) -> str:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            all_arrived.set()
        await all_arrived.wait()
        return SEAL

    lifecycle = OntologyIndexLifecycle(store=state, admit=admit, clock=lambda: NOW)
    commands = (_command(), _command(command_id="competing-command", target=_generation(2)))
    results = await asyncio.gather(
        *(lifecycle.apply(item) for item in commands), return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    pointer = await lifecycle.read(_scope())
    assert pointer.revision == 1
    assert pointer.terminal is not None
    assert await lifecycle.apply(pointer.terminal.command) == pointer.terminal


async def test_pointer_and_terminal_survive_interruption_before_archive() -> None:
    class InterruptedStore(InMemoryStateStore):
        fail = True

        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            if self.fail and ":result:" in key:
                raise RuntimeError("archive unavailable")
            return await super().write_state_if_absent(key, value)

    state = InterruptedStore()
    lifecycle = OntologyIndexLifecycle(
        store=state, admit=AsyncMock(return_value=SEAL), clock=lambda: NOW
    )
    command = _command()
    with pytest.raises(RuntimeError, match="archive unavailable"):
        await lifecycle.apply(command)
    pointer = await lifecycle.read(_scope())
    assert pointer.active == _generation()
    assert pointer.terminal is not None
    state.fail = False
    restarted = OntologyIndexLifecycle(
        store=state, admit=AsyncMock(return_value=SEAL), clock=lambda: NOW
    )
    second = _command(
        command_id="successor",
        target=_generation(2),
        expected_revision=1,
        expected_active_digest=_generation().digest,
    )
    await restarted.apply(second)
    assert await restarted.apply(command) == pointer.terminal
    assert (await restarted.read(_scope())).active == _generation(2)


async def test_invalidation_rollback_and_retirement_preserve_exact_retained_identities() -> None:
    state = InMemoryStateStore()
    lifecycle = OntologyIndexLifecycle(
        store=state, admit=AsyncMock(return_value=SEAL), clock=lambda: NOW
    )
    await lifecycle.apply(_command())
    await lifecycle.apply(
        _command(
            command_id="replacement",
            target=_generation(2),
            expected_revision=1,
            expected_active_digest=_generation().digest,
        )
    )
    await lifecycle.apply(
        _command(
            command_id="rollback",
            operation="rollback",
            target=_generation(),
            expected_revision=2,
            expected_active_digest=_generation(2).digest,
        )
    )
    pointer = await lifecycle.read(_scope())
    assert pointer.active == _generation()
    assert pointer.retained == (_generation(2),)
    await lifecycle.apply(
        _command(
            command_id="invalidation",
            operation="invalidate",
            target=None,
            expected_revision=3,
            expected_active_digest=_generation().digest,
        )
    )
    assert (await lifecycle.read(_scope())).active is None
    await lifecycle.apply(
        _command(
            command_id="retirement",
            operation="retire",
            target=_generation(),
            expected_revision=4,
            expected_active_digest=None,
        )
    )
    with pytest.raises(ValueError, match="retained"):
        await lifecycle.apply(
            _command(
                command_id="retired-rollback",
                operation="rollback",
                target=_generation(),
                expected_revision=5,
                expected_active_digest=None,
            )
        )
    assert (await lifecycle.read(_scope())).retained == (_generation(2),)
    with pytest.raises(ValueError, match="retired"):
        await lifecycle.apply(
            _command(
                command_id="retired-reactivation",
                target=_generation(),
                expected_revision=5,
                expected_active_digest=None,
            )
        )
    refreshed = _generation().model_copy(
        update={"validation_receipt_digest": content_digest("new-validation")}
    )
    with pytest.raises(ValueError, match="retired"):
        await lifecycle.apply(
            _command(
                command_id="rehashed-retired",
                target=refreshed,
                expected_revision=5,
                expected_active_digest=None,
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_revision": True},
        {"execution_authority": True},
        {"expires_at": NOW + timedelta(seconds=121)},
        {"scope": _scope("different-reader")},
        {"operation": "invalidate"},
    ],
)
def test_transition_rejects_authority_scope_and_unbounded_inputs(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _command(**changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", 9),
        ("active_digest", content_digest("forged-active")),
        ("applied_at", (NOW + timedelta(minutes=2)).isoformat()),
    ],
)
async def test_terminal_archive_tampering_is_rejected_before_replay(field: str, value: Any) -> None:
    state = InMemoryStateStore()
    lifecycle = OntologyIndexLifecycle(
        store=state, admit=AsyncMock(return_value=SEAL), clock=lambda: NOW
    )
    await lifecycle.apply(_command())
    key = next(key for key in state._state if ":result:" in key)
    raw = dict(state._state[key])
    raw[field] = value
    await state.write_state(key, raw)
    with pytest.raises(ValueError, match="validation"):
        await lifecycle.apply(_command())


@pytest.mark.integration
async def test_postgres_pointer_reconnect_and_concurrent_cas() -> None:
    import psycopg
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN")
    if not dsn:
        pytest.skip("FDAI_ONTOLOGY_SNAPSHOT_TEST_DSN is unset")
    options = conninfo_to_dict(dsn)
    assert options.get("host") in {"localhost", "127.0.0.1", "::1"}
    assert options.get("hostaddr", options["host"]) in {"localhost", "127.0.0.1", "::1"}
    owned_keys: list[str] = []

    class TrackedStore(PostgresStateStore):
        async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool:
            owned_keys.append(key)
            return await super().write_state_if_absent(key, value)

        async def compare_and_set_state(
            self,
            key: str,
            value: Mapping[str, Any],
            *,
            expected_revision: int,
        ) -> bool:
            owned_keys.append(key)
            return await super().compare_and_set_state(
                key, value, expected_revision=expected_revision
            )

    config = PostgresStateStoreConfig(dsn=dsn, connect_timeout_s=3, statement_timeout_ms=3000)
    scope = _scope(f"lifecycle-integration-{uuid.uuid4().hex}")
    first = _generation().model_copy(
        update={
            "scope": scope,
            "snapshot_digest": content_digest((scope.digest, "snapshot-1")),
            "vector_digest": content_digest((scope.digest, "vector-1")),
        }
    )
    second = _generation(2).model_copy(
        update={
            "scope": scope,
            "snapshot_digest": content_digest((scope.digest, "snapshot-2")),
            "vector_digest": content_digest((scope.digest, "vector-2")),
        }
    )
    commands = (
        _command(scope=scope, target=first),
        _command(scope=scope, target=second, command_id="competing-command"),
    )
    arrived = 0
    all_arrived = asyncio.Event()

    async def admit(_command: IndexTransition) -> str:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            all_arrived.set()
        await all_arrived.wait()
        return SEAL

    try:
        replicas = tuple(
            OntologyIndexLifecycle(
                store=TrackedStore(config=config), admit=admit, clock=lambda: NOW
            )
            for _ in commands
        )
        results = await asyncio.gather(
            *(replica.apply(command) for replica, command in zip(replicas, commands, strict=True)),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ValueError) for result in results) == 1
        reader = OntologyIndexLifecycle(
            store=TrackedStore(config=config),
            admit=AsyncMock(return_value=SEAL),
            clock=lambda: NOW,
        )
        pointer = await reader.read(scope)
        assert pointer.revision == 1
        assert pointer.terminal is not None
        assert await reader.apply(pointer.terminal.command) == pointer.terminal
        target = pointer.active
        assert target is not None
        store = TrackedStore(config=config)
        with pytest.raises(ValueError, match="retired terminal"):
            await reclaim_retired_index(store=store, lifecycle=reader, target=target)
        invalidation = _command(
            scope=scope,
            command_id="invalidation",
            operation="invalidate",
            target=None,
            expected_revision=1,
            expected_active_digest=target.digest,
        )
        await reader.apply(invalidation)
        retirement = _command(
            scope=scope,
            command_id="retirement",
            operation="retire",
            target=target,
            expected_revision=2,
            expected_active_digest=None,
        )
        terminal = await reader.apply(retirement)
        await store.write_state_if_absent(
            f"ontology-context-evidence:v1:terminal-seal:{retirement.digest}",
            {"terminal": terminal.model_dump(mode="json"), "terminal_seal_digest": SEAL},
        )
        binding = _digest(
            {
                "snapshot_digest": target.snapshot_digest,
                "generation_digest": target.generation_digest,
            }
        )
        for prefix in (
            f"ontology-semantic-snapshot:v1:{target.snapshot_digest}:",
            f"ontology-semantic-vectors:v1:{binding}:",
            f"ontology-semantic-vectors:v1:{target.vector_digest}:",
        ):
            await store.write_state_if_absent(prefix + "synthetic-row", {"synthetic": True})
        assert await reclaim_retired_index(store=store, lifecycle=reader, target=target) == 3
        assert await reclaim_retired_index(store=store, lifecycle=reader, target=target) == 0
    finally:
        if owned_keys:
            async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=3) as connection:
                await connection.execute("DELETE FROM state_kv WHERE key=ANY(%s)", (owned_keys,))
