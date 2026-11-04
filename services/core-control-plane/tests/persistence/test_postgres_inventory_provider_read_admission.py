"""Tests for durable shared inventory provider-read admission and cooldown (#2329)."""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import psycopg
import pytest
from fdai.delivery.azure import arg_transport, arm_inventory_transport
from fdai.delivery.azure.arm_inventory_transport import fetch_arm_json
from fdai.delivery.azure.arm_inventory_vm_state import ArmInventoryError
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync_cli_support import (
    build_sources,
    complete_durable_admission_generation,
    prepare_durable_admission_sources_kwargs,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_provider_read_admission import (
    DurableProviderReadAdmissionGate,
    ProviderReadAdmissionUnavailableError,
    ProviderReadBudgetExhaustedError,
    ProviderReadCooldownActiveError,
    ProviderReadScopeBinding,
    StaleProviderReadGenerationError,
    complete_collection_generation,
    resolve_or_allocate_collection_generation,
)
from fdai.shared.providers.inventory import Inventory
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def _binding(
    *,
    source_name: str = "arg",
    generation_id: str = "gen-1",
    generation_seq: int = 1,
) -> ProviderReadScopeBinding:
    return ProviderReadScopeBinding(
        source_name=source_name,
        authentication_selector_digest="sha256:" + "1" * 64,
        scope_universe_digest="sha256:" + "2" * 64,
        policy_digest="sha256:" + "3" * 64,
        generation_id=generation_id,
        generation_seq=generation_seq,
    )


@pytest.mark.asyncio
async def test_durable_arg_throttle_gate_shares_cooldown_across_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_now = [NOW]
    waits: list[float] = []

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)
        clock_now[0] = clock_now[0] + timedelta(seconds=delay)

    monkeypatch.setattr(arg_transport, "_monotonic", lambda: 0.0)
    monkeypatch.setattr(arg_transport, "_sleep", fake_sleep)

    store = InMemoryStateStore()
    durable_a = DurableProviderReadAdmissionGate(
        state_store=store,
        binding=_binding(source_name="arg"),
        clock=lambda: clock_now[0],
        sleep=fake_sleep,
    )
    durable_b = DurableProviderReadAdmissionGate(
        state_store=store,
        binding=_binding(source_name="arg"),
        clock=lambda: clock_now[0],
        sleep=fake_sleep,
    )

    with pytest.raises(ValueError, match="requires a bound DurableProviderReadAdmissionGate"):
        arg_transport.ArgThrottleGate(require_durable_admission=True)

    original = arg_transport.ArgThrottleGate(
        durable_gate=durable_a,
        require_durable_admission=True,
    )
    await original.defer(20.0)

    # A replacement gate bound to the same durable store observes the 20s cooldown.
    replacement = arg_transport.ArgThrottleGate(
        durable_gate=durable_b,
        require_durable_admission=True,
    )
    await replacement.wait()
    assert waits == [20.0]


@pytest.mark.asyncio
async def test_durable_arm_retry_after_is_retained_and_enforced_by_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_now = [NOW]
    waits: list[float] = []
    calls = 0

    class Clock:
        @staticmethod
        def now(_: object) -> datetime:
            return clock_now[0]

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)
        clock_now[0] = clock_now[0] + timedelta(seconds=delay)

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, json={"value": []})

    monkeypatch.setattr(arm_inventory_transport, "_sleep", fake_sleep)
    monkeypatch.setattr(arm_inventory_transport, "datetime", Clock)

    store = InMemoryStateStore()
    gate = DurableProviderReadAdmissionGate(
        state_store=store,
        binding=_binding(source_name="arm"),
        max_defer_seconds=120.0,
        clock=lambda: clock_now[0],
        sleep=fake_sleep,
    )

    with pytest.raises(ValueError, match="requires a bound DurableProviderReadAdmissionGate"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await fetch_arm_json(
                client=client,
                url="https://management.example.invalid/resources",
                headers={},
                resource_type="resource-group",
                timeout_seconds=1.0,
                max_response_bytes=1024,
                max_attempts=1,
                require_durable_admission=True,
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        fetch = partial(
            fetch_arm_json,
            client=client,
            url="https://management.example.invalid/resources",
            headers={},
            resource_type="resource-group",
            timeout_seconds=1.0,
            max_response_bytes=1024,
            max_attempts=1,
            durable_gate=gate,
            require_durable_admission=True,
        )
        with pytest.raises(ArmInventoryError) as failure:
            await fetch()
        assert failure.value.retry_not_before == NOW + timedelta(seconds=120)

        # Next read on a replacement gate sharing the same StateStore waits 120s before calling ARM.
        replacement_gate = DurableProviderReadAdmissionGate(
            state_store=store,
            binding=_binding(source_name="arm"),
            max_defer_seconds=120.0,
            clock=lambda: clock_now[0],
            sleep=fake_sleep,
        )
        payload, _ = await fetch(durable_gate=replacement_gate)

        # Replaying the completed read on the same generation returns the retained payload
        # WITHOUT making a third HTTP request.
        replayed_payload, _ = await fetch(durable_gate=replacement_gate)

    assert payload == {"value": []}
    assert replayed_payload == {"value": []}
    assert calls == 2
    assert waits == [120.0]
    accounting = await replacement_gate.snapshot_accounting()
    assert accounting["requests_admitted"] == 2
    assert accounting["requests_reused"] == 1
    assert accounting["ambiguous_or_cancelled_count"] == 1


@pytest.mark.parametrize("source_name", ["arg", "arm"])
@pytest.mark.asyncio
async def test_build_sources_wires_durable_admission_and_replays_without_second_http_call(
    source_name: str,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_INVENTORY_SOURCES": source_name,
            "FDAI_INVENTORY_RESOURCE_TYPES": "resource-group",
        }
    )
    provider_calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        if request.url.host == "identity.example.invalid":
            return httpx.Response(
                200,
                json={"access_token": "synthetic-token", "expires_on": 1_893_456_000},
            )
        provider_calls += 1
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"},
            )
        return httpx.Response(200, json={"value": []})

    store = InMemoryStateStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        identity = ManagedIdentityWorkloadIdentity(
            http_client=client,
            config=ManagedIdentityWorkloadIdentityConfig(
                endpoint="https://identity.example.invalid/token",
                header="synthetic-header",
                client_id="00000000-0000-0000-0000-000000000001",
            ),
        )
        # Missing admission_state_store when require_durable_admission=True fails closed.
        with pytest.raises(ValueError, match="requires admission_state_store"):
            build_sources(
                config=config,
                vocabulary=load_resource_type_registry(),
                resource_types=("resource-group",),
                identity=identity,
                http_client=client,
                started_at=NOW,
                require_durable_admission=True,
            )

        (source_1,) = build_sources(
            config=config,
            vocabulary=load_resource_type_registry(),
            resource_types=("resource-group",),
            identity=identity,
            http_client=client,
            started_at=NOW,
            admission_state_store=store,
            generation_id="gen-adapter-1",
            generation_seq=1,
            require_durable_admission=True,
        )
        batches_1 = [batch async for batch in cast(Inventory, source_1.inventory).full_snapshot()]
        assert batches_1
        first_call_count = provider_calls
        assert first_call_count >= 1

        # Rebuilding the source for the same generation reuses retained provider responses
        # without issuing any additional provider HTTP calls.
        (source_replay,) = build_sources(
            config=config,
            vocabulary=load_resource_type_registry(),
            resource_types=("resource-group",),
            identity=identity,
            http_client=client,
            started_at=NOW,
            admission_state_store=store,
            generation_id="gen-adapter-1",
            generation_seq=1,
            require_durable_admission=True,
        )
        batches_replay = [
            batch async for batch in cast(Inventory, source_replay.inventory).full_snapshot()
        ]
        assert batches_replay
        assert provider_calls == first_call_count


@pytest.mark.asyncio
async def test_budget_limit_reuse_cancellation_stale_generation_and_unavailable_store() -> None:
    store = InMemoryStateStore()
    gate = DurableProviderReadAdmissionGate(
        state_store=store,
        binding=_binding(source_name="arg", generation_id="gen-1", generation_seq=1),
        max_requests_per_generation=2,
        clock=lambda: NOW,
    )

    # 1. First request admitted and completed.
    r1 = await gate.acquire(request_id="req-1", idempotency_key="idem-1")
    assert r1.reused is False
    assert r1.requests_admitted == 1
    await gate.complete(
        request_id="req-1",
        idempotency_key="idem-1",
        response_digest="sha256:" + "a" * 64,
    )

    # 2. Within-generation replay reuses completed digest without consuming budget.
    r1_replay = await gate.acquire(request_id="req-1", idempotency_key="idem-1")
    assert r1_replay.reused is True
    assert r1_replay.reused_response_digest == "sha256:" + "a" * 64
    assert r1_replay.requests_admitted == 1
    assert r1_replay.requests_reused == 1

    # 3. Second physical request admitted, then cancelled -> does NOT replenish capacity!
    r2 = await gate.acquire(request_id="req-2", idempotency_key="idem-2")
    assert r2.requests_admitted == 2
    await gate.record_ambiguous_or_cancelled(request_id="req-2", reason="cancelled")

    # 4. Third physical request hits exact limit (2/2) and records an explicit hold.
    with pytest.raises(ProviderReadBudgetExhaustedError, match="2/2"):
        await gate.acquire(request_id="req-3", idempotency_key="idem-3")
    snap = await gate.snapshot_accounting()
    assert snap["requests_admitted"] == 2
    assert snap["ambiguous_or_cancelled_count"] == 1
    assert snap["requests_held"] == 1

    # 5. Advance to generation 2 while preserving active cooldown.
    await gate.defer(45.0, now=NOW)
    gate_gen2 = DurableProviderReadAdmissionGate(
        state_store=store,
        binding=_binding(source_name="arg", generation_id="gen-2", generation_seq=2),
        max_requests_per_generation=2,
        clock=lambda: NOW,
    )
    with pytest.raises(ProviderReadCooldownActiveError):
        await gate_gen2.acquire(
            request_id="req-g2-1",
            idempotency_key="idem-g2-1",
            wait_for_cooldown=False,
            now=NOW + timedelta(seconds=10),
        )
    r_g2 = await gate_gen2.acquire(
        request_id="req-g2-1",
        idempotency_key="idem-g2-1",
        wait_for_cooldown=False,
        now=NOW + timedelta(seconds=60),
    )
    assert r_g2.requests_admitted == 1

    # 6. Stale generation 1 fails closed without replenishing or mutating generation 2.
    with pytest.raises(StaleProviderReadGenerationError, match="superseded"):
        await gate.acquire(
            request_id="req-stale",
            idempotency_key="idem-stale",
            now=NOW + timedelta(seconds=60),
        )

    # 7. Unavailable storage fails closed without an accepting fallback.
    class _FailingStore(InMemoryStateStore):
        async def read_state(self, _key: str) -> dict[str, Any] | None:
            raise OSError("database unreachable")

    broken_gate = DurableProviderReadAdmissionGate(
        state_store=_FailingStore(),
        binding=_binding(source_name="arg"),
        clock=lambda: NOW,
    )
    with pytest.raises(ProviderReadAdmissionUnavailableError, match="OSError"):
        await broken_gate.acquire(request_id="req-x", idempotency_key="idem-x")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_provider_read_admission_concurrency_and_restart_persistence() -> None:
    raw_dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw_dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    normalized = raw_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.port == 5433

    schema = f"provider_read_adm_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(normalized, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        scoped_dsn = make_conninfo(normalized, options=f"-c search_path={schema},public")
        try:
            async with await psycopg.AsyncConnection.connect(
                scoped_dsn, autocommit=True
            ) as setup_conn:
                await setup_conn.execute(
                    """
                    CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY,
                        event_id UUID NOT NULL,
                        correlation_id TEXT,
                        actor TEXT NOT NULL,
                        action_kind TEXT NOT NULL,
                        mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')),
                        entry JSONB NOT NULL,
                        previous_hash TEXT NOT NULL,
                        entry_hash TEXT NOT NULL UNIQUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )

            store_a = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            store_b = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            try:
                gate_a = DurableProviderReadAdmissionGate(
                    state_store=store_a,
                    binding=_binding(source_name="arg", generation_id="pg-gen-1", generation_seq=1),
                    max_requests_per_generation=4,
                    clock=lambda: NOW,
                )
                gate_b = DurableProviderReadAdmissionGate(
                    state_store=store_b,
                    binding=_binding(source_name="arg", generation_id="pg-gen-1", generation_seq=1),
                    max_requests_per_generation=4,
                    clock=lambda: NOW,
                )

                # Concurrent requests across two Postgres-backed gates enforce the exact limit of 4.
                outcomes = await asyncio.gather(
                    *(
                        (gate_a if idx % 2 == 0 else gate_b).acquire(
                            request_id=f"pg-req-{idx}",
                            idempotency_key=f"pg-idem-{idx}",
                        )
                        for idx in range(6)
                    ),
                    return_exceptions=True,
                )
                admitted = [o for o in outcomes if not isinstance(o, BaseException)]
                exhausted = [o for o in outcomes if isinstance(o, ProviderReadBudgetExhaustedError)]
                assert len(admitted) == 4
                assert len(exhausted) == 2

                await gate_a.defer(90.0, now=NOW)
            finally:
                await store_a.aclose()
                await store_b.aclose()

            # Cold process restart reconstructs exact accounting and cooldown from PostgreSQL,
            # and resolve_or_allocate_collection_generation resumes unfinished or allocates next.
            store_restart = PostgresStateStore(config=PostgresStateStoreConfig(dsn=scoped_dsn))
            try:
                gen_1, seq_1 = await resolve_or_allocate_collection_generation(
                    store_restart,
                    scope_ref="sub-1",
                )
                assert (gen_1, seq_1) == ("collection-gen-000001", 1)
                # Restart while status is still "in_progress" (with no unfinished_generation_id arg)
                # resumes the same generation and sequence rather than advancing.
                resumed_id, resumed_seq = await resolve_or_allocate_collection_generation(
                    store_restart,
                    scope_ref="sub-1",
                )
                assert (resumed_id, resumed_seq) == ("collection-gen-000001", 1)
                # Mark generation 1 completed, then next run allocates seq 2.
                await complete_collection_generation(
                    store_restart,
                    scope_ref="sub-1",
                    generation_id=gen_1,
                    generation_seq=seq_1,
                )
                next_id, next_seq = await resolve_or_allocate_collection_generation(
                    store_restart,
                    scope_ref="sub-1",
                )
                assert (next_id, next_seq) == ("collection-gen-000002", 2)

                # Exercise prepare_durable_admission_sources_kwargs across an unfinished restart
                # and completion on PostgreSQL.
                async with (
                    AsyncExitStack() as stack,
                    httpx.AsyncClient(
                        transport=httpx.MockTransport(lambda _: httpx.Response(200))
                    ) as client,
                ):
                    mi = ManagedIdentityWorkloadIdentity(
                        http_client=client,
                        config=ManagedIdentityWorkloadIdentityConfig(
                            endpoint="https://identity.example.invalid/token",
                            header="synthetic-header",
                            client_id="00000000-0000-0000-0000-000000000001",
                        ),
                    )
                    # Because seq 2 is still in_progress, prepare_durable_admission_sources_kwargs
                    # resumes seq 2 automatically on restart.
                    kwargs_resumed = await prepare_durable_admission_sources_kwargs(
                        dsn=scoped_dsn,
                        scopes=("sub-1",),
                        identity=mi,
                        stack=stack,
                    )
                    assert kwargs_resumed["generation_id"] == "collection-gen-000002"
                    assert kwargs_resumed["generation_seq"] == 2
                    assert kwargs_resumed["require_durable_admission"] is True

                    await complete_durable_admission_generation(
                        scopes=("sub-1",),
                        admission_kwargs=kwargs_resumed,
                    )
                    kwargs_next = await prepare_durable_admission_sources_kwargs(
                        dsn=scoped_dsn,
                        scopes=("sub-1",),
                        identity=mi,
                        stack=stack,
                        current_active_snapshot_id="snap-baseline-3",
                    )
                    assert kwargs_next["generation_id"] == "collection-gen-000003"
                    assert kwargs_next["generation_seq"] == 3

                    # Simulate a crash after promotion changed active_snapshot_id
                    # BEFORE complete_durable_admission_generation was called: startup reconciles
                    # against current_active_snapshot_id and advances to seq 4!
                    kwargs_reconciled = await prepare_durable_admission_sources_kwargs(
                        dsn=scoped_dsn,
                        scopes=("sub-1",),
                        identity=mi,
                        stack=stack,
                        current_active_snapshot_id="snap-promoted-3",
                    )
                    assert kwargs_reconciled["generation_id"] == "collection-gen-000004"
                    assert kwargs_reconciled["generation_seq"] == 4

                    # Simulate a handled collection failure (status="failed") with no snapshot
                    # promotion: next run advances to seq 5 instead of getting stuck on seq 4!
                    await complete_durable_admission_generation(
                        scopes=("sub-1",),
                        admission_kwargs=kwargs_reconciled,
                        terminal_status="failed",
                    )
                    kwargs_after_failure = await prepare_durable_admission_sources_kwargs(
                        dsn=scoped_dsn,
                        scopes=("sub-1",),
                        identity=mi,
                        stack=stack,
                        current_active_snapshot_id="snap-promoted-3",
                    )
                    assert kwargs_after_failure["generation_id"] == "collection-gen-000005"
                    assert kwargs_after_failure["generation_seq"] == 5

                gate_restart = DurableProviderReadAdmissionGate(
                    state_store=store_restart,
                    binding=_binding(source_name="arg", generation_id="pg-gen-1", generation_seq=1),
                    max_requests_per_generation=4,
                    clock=lambda: NOW,
                )
                snap = await gate_restart.snapshot_accounting()
                assert snap["requests_admitted"] == 4
                assert snap["requests_held"] == 2
                assert snap["cooldown_not_before"] == (NOW + timedelta(seconds=90)).isoformat()
            finally:
                await store_restart.aclose()
        finally:
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
