"""Shared behavioural assertions for fake, PostgreSQL, and Redpanda providers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import psycopg
import pytest
from fdai.shared.providers import (
    EventBus,
    EventEnvelope,
    SecretNotFoundError,
    SecretProvider,
    StateStore,
    WorkloadIdentity,
)
from fdai.shared.providers.testing import (
    InMemorySecretProvider,
    InMemoryStateStore,
    StaticWorkloadIdentity,
)

SECRET_PROVIDER_FACTORIES: list[Callable[[SecretProvider], SecretProvider]] = [
    lambda p: p,
]


class EventBusTestHarness(Protocol):
    bus: EventBus

    def topic(self, suffix: str) -> str: ...

    def group(self, suffix: str) -> str: ...

    async def collect(
        self,
        topic: str,
        group: str,
        *,
        expected_count: int,
    ) -> tuple[EventEnvelope, ...]: ...


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------


async def test_state_store_write_then_read_returns_same_value(
    state_store: StateStore,
) -> None:
    await state_store.write_state("event:1", {"tier": "t0", "decision": "auto"})
    got = await state_store.read_state("event:1")
    assert got == {"tier": "t0", "decision": "auto"}


async def test_state_store_read_missing_returns_none(
    state_store: StateStore,
) -> None:
    assert await state_store.read_state("nothing-here") is None


async def test_state_store_audit_chain_is_intact_after_appends(
    state_store: StateStore,
) -> None:
    for i in range(3):
        await state_store.append_audit_entry({"event_id": f"evt-{i}", "decision": "auto"})
    assert await state_store.verify_chain() is True


async def test_state_store_duplicate_delivery_is_a_no_op(state_store: StateStore) -> None:
    assert await state_store.write_state_if_absent("delivery:1", {"attempt": 1}) is True
    assert await state_store.write_state_if_absent("delivery:1", {"attempt": 2}) is False
    assert await state_store.read_state("delivery:1") == {"attempt": 1}


async def test_in_memory_state_store_verify_chain_detects_tampered_previous_hash() -> None:
    """Tampering with a stored `previous_hash` MUST make `verify_chain()` fail.

    Guards against a silent audit-chain corruption escaping detection.
    """
    store = InMemoryStateStore()
    await store.append_audit_entry({"event_id": "e-1"})
    await store.append_audit_entry({"event_id": "e-2"})
    # Mutate the internal chain directly - the invariant we're checking is
    # that the verifier catches it, not that a public API allows it.
    store._audit[1]["previous_hash"] = "sha256:tampered"  # noqa: SLF001
    assert await store.verify_chain() is False


async def test_in_memory_state_store_verify_chain_detects_tampered_entry_hash() -> None:
    """Tampering with a stored `entry_hash` MUST make `verify_chain()` fail."""
    store = InMemoryStateStore()
    await store.append_audit_entry({"event_id": "e-1"})
    await store.append_audit_entry({"event_id": "e-2"})
    # Recompute previous_hash chain but corrupt the second entry's own hash.
    store._audit[1]["entry_hash"] = "sha256:not-the-real-hash"  # noqa: SLF001
    assert await store.verify_chain() is False


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


async def test_event_bus_publish_receipt_has_monotonic_offsets(
    event_bus_harness: EventBusTestHarness,
) -> None:
    topic = event_bus_harness.topic("change-events")
    r1 = await event_bus_harness.bus.publish(topic, "rg-example", {"n": 1})
    r2 = await event_bus_harness.bus.publish(topic, "rg-example", {"n": 2})
    assert r1.topic == topic
    assert r2.topic == topic
    if r1.offset is not None and r2.offset is not None:
        assert r2.offset > r1.offset


async def test_event_bus_subscribe_returns_publish_order(
    event_bus_harness: EventBusTestHarness,
) -> None:
    bus = event_bus_harness.bus
    topic = event_bus_harness.topic("change-events")
    group = event_bus_harness.group("group-a")
    for i in range(3):
        await bus.publish(topic, f"key-{i}", {"n": i})
    got = [
        int(envelope.payload["n"])
        for envelope in await event_bus_harness.collect(topic, group, expected_count=3)
    ]
    assert got == [0, 1, 2]


async def test_event_bus_two_groups_see_same_messages(
    event_bus_harness: EventBusTestHarness,
) -> None:
    bus = event_bus_harness.bus
    topic = event_bus_harness.topic("change-events")
    await bus.publish(topic, "k", {"n": 1})
    await bus.publish(topic, "k", {"n": 2})
    a = [
        int(envelope.payload["n"])
        for envelope in await event_bus_harness.collect(
            topic,
            event_bus_harness.group("group-a"),
            expected_count=2,
        )
    ]
    b = [
        int(envelope.payload["n"])
        for envelope in await event_bus_harness.collect(
            topic,
            event_bus_harness.group("group-b"),
            expected_count=2,
        )
    ]
    assert a == [1, 2]
    assert b == [1, 2]


async def test_event_bus_same_group_resumes_from_committed_offset(
    event_bus_harness: EventBusTestHarness,
) -> None:
    bus = event_bus_harness.bus
    topic = event_bus_harness.topic("change-events")
    group = event_bus_harness.group("group-a")
    await bus.publish(topic, "k", {"n": 1})
    await bus.publish(topic, "k", {"n": 2})
    first_pass = [
        int(envelope.payload["n"])
        for envelope in await event_bus_harness.collect(topic, group, expected_count=2)
    ]
    assert first_pass == [1, 2]

    second_pass = await event_bus_harness.collect(topic, group, expected_count=0)
    assert second_pass == ()

    await bus.publish(topic, "k", {"n": 3})
    third_pass = [
        int(envelope.payload["n"])
        for envelope in await event_bus_harness.collect(topic, group, expected_count=1)
    ]
    assert third_pass == [3]


async def test_event_bus_dead_letter_uses_topic_dlq_convention(
    event_bus_harness: EventBusTestHarness,
) -> None:
    bus = event_bus_harness.bus
    topic = event_bus_harness.topic("change-events")
    await bus.publish(topic, "k", {"n": 1})
    await bus.dead_letter(topic, "k", {"n": 1}, reason="poison")
    envelopes = await event_bus_harness.collect(
        f"{topic}.dlq",
        event_bus_harness.group("auditor"),
        expected_count=1,
    )
    assert len(envelopes) == 1
    assert envelopes[0].topic == f"{topic}.dlq"
    assert envelopes[0].payload["original_topic"] == topic
    assert envelopes[0].payload["reason"] == "poison"


@pytest.mark.integration
async def test_postgres_pgvector_creation_and_query(
    provider_contract_postgres_dsn: str | None,
) -> None:
    if provider_contract_postgres_dsn is None:
        pytest.skip("real provider matrix is not selected")
    async with await psycopg.AsyncConnection.connect(provider_contract_postgres_dsn) as connection:
        await connection.execute("CREATE TEMP TABLE provider_vectors (embedding vector(3))")
        await connection.execute(
            "INSERT INTO provider_vectors (embedding) VALUES ('[1,0,0]'), ('[0,1,0]')"
        )
        cursor = await connection.execute(
            "SELECT embedding::text FROM provider_vectors ORDER BY embedding <=> '[1,0,0]' LIMIT 1"
        )
        assert await cursor.fetchone() == ("[1,0,0]",)


# ---------------------------------------------------------------------------
# SecretProvider
# ---------------------------------------------------------------------------


def _build_seeded_secret_provider() -> SecretProvider:
    return InMemorySecretProvider({"kv/example": "value"})


@pytest.mark.parametrize("factory", SECRET_PROVIDER_FACTORIES)
async def test_secret_provider_returns_registered_secret(
    factory: Callable[[SecretProvider], SecretProvider],
) -> None:
    provider = factory(_build_seeded_secret_provider())
    assert await provider.get("kv/example") == "value"


@pytest.mark.parametrize("factory", SECRET_PROVIDER_FACTORIES)
async def test_secret_provider_raises_on_missing(
    factory: Callable[[SecretProvider], SecretProvider],
) -> None:
    provider = factory(_build_seeded_secret_provider())
    with pytest.raises(SecretNotFoundError):
        await provider.get("kv/does-not-exist")


async def test_in_memory_secret_provider_register_adds_secret() -> None:
    """`register()` is the test-setup helper documented on the fake.

    Regression guard so it stays hooked up to `_secrets` (a rename that
    silently broke this would leave every fork's test suite unable to
    add seeds after construction).
    """
    provider = InMemorySecretProvider()
    provider.register("kv/late-added", "hello")
    assert await provider.get("kv/late-added") == "hello"


# ---------------------------------------------------------------------------
# WorkloadIdentity
# ---------------------------------------------------------------------------


async def test_workload_identity_returns_aware_expiry() -> None:
    wi: WorkloadIdentity = StaticWorkloadIdentity(audience="aud-a")
    token = await wi.get_token("aud-a")
    assert token.audience == "aud-a"
    assert token.expires_at.tzinfo is not None
    assert token.expires_at > datetime.now(tz=UTC)


async def test_workload_identity_denies_cross_audience() -> None:
    wi: WorkloadIdentity = StaticWorkloadIdentity(audience="aud-a")
    with pytest.raises(ValueError):
        await wi.get_token("aud-b")
