"""Behavioural contract tests for the four provider Protocols.

The whole point of these tests is that **the same file** runs against
every backend that claims to satisfy a Protocol. Today only the shipped
in-memory fakes are registered; the Postgres StateStore (W1.5) and the
Redpanda / Event Hubs EventBus (W6.3) will register themselves once they
land, and they inherit this suite.

Each provider factory is a zero-arg callable that hands back a fresh
instance - tests never share state between runs.

All provider methods are async by contract, so every test function here
is ``async def``; pytest-asyncio's ``asyncio_mode = "auto"`` picks them up.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from aiopspilot.shared.providers import (
    EventBus,
    SecretNotFoundError,
    SecretProvider,
    StateStore,
    WorkloadIdentity,
)
from aiopspilot.shared.providers.testing import (
    InMemoryEventBus,
    InMemorySecretProvider,
    InMemoryStateStore,
    StaticWorkloadIdentity,
)

# ---------------------------------------------------------------------------
# Provider factories (add real adapters here once they exist).
# ---------------------------------------------------------------------------

STATE_STORE_FACTORIES: list[Callable[[], StateStore]] = [
    lambda: InMemoryStateStore(),
]
"""New adapters MUST append themselves here (or via pytest_generate_tests)."""

EVENT_BUS_FACTORIES: list[Callable[[], EventBus]] = [
    lambda: InMemoryEventBus(),
]

SECRET_PROVIDER_FACTORIES: list[Callable[[SecretProvider], SecretProvider]] = [
    lambda p: p,
]


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", STATE_STORE_FACTORIES)
async def test_state_store_write_then_read_returns_same_value(
    factory: Callable[[], StateStore],
) -> None:
    store = factory()
    await store.write_state("event:1", {"tier": "t0", "decision": "auto"})
    got = await store.read_state("event:1")
    assert got == {"tier": "t0", "decision": "auto"}


@pytest.mark.parametrize("factory", STATE_STORE_FACTORIES)
async def test_state_store_read_missing_returns_none(
    factory: Callable[[], StateStore],
) -> None:
    store = factory()
    assert await store.read_state("nothing-here") is None


@pytest.mark.parametrize("factory", STATE_STORE_FACTORIES)
async def test_state_store_audit_chain_is_intact_after_appends(
    factory: Callable[[], StateStore],
) -> None:
    store = factory()
    for i in range(3):
        await store.append_audit_entry({"event_id": f"evt-{i}", "decision": "auto"})

    if isinstance(store, InMemoryStateStore):
        assert store.verify_chain() is True
        entries = list(store.audit_entries)
        assert len(entries) == 3
        for i in range(1, 3):
            assert entries[i]["previous_hash"] == entries[i - 1]["entry_hash"]


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
    assert store.verify_chain() is False


async def test_in_memory_state_store_verify_chain_detects_tampered_entry_hash() -> None:
    """Tampering with a stored `entry_hash` MUST make `verify_chain()` fail."""
    store = InMemoryStateStore()
    await store.append_audit_entry({"event_id": "e-1"})
    await store.append_audit_entry({"event_id": "e-2"})
    # Recompute previous_hash chain but corrupt the second entry's own hash.
    store._audit[1]["entry_hash"] = "sha256:not-the-real-hash"  # noqa: SLF001
    assert store.verify_chain() is False


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", EVENT_BUS_FACTORIES)
async def test_event_bus_publish_receipt_has_monotonic_offsets(
    factory: Callable[[], EventBus],
) -> None:
    bus = factory()
    r1 = await bus.publish("aw.change.events", "rg-example", {"n": 1})
    r2 = await bus.publish("aw.change.events", "rg-example", {"n": 2})
    assert r1.topic == "aw.change.events"
    assert r2.topic == "aw.change.events"
    if r1.offset is not None and r2.offset is not None:
        assert r2.offset > r1.offset


@pytest.mark.parametrize("factory", EVENT_BUS_FACTORIES)
async def test_event_bus_subscribe_returns_publish_order(
    factory: Callable[[], EventBus],
) -> None:
    bus = factory()
    for i in range(3):
        await bus.publish("aw.change.events", f"key-{i}", {"n": i})

    got: list[int] = []
    async for envelope in bus.subscribe("aw.change.events", "group-a"):
        got.append(int(envelope.payload["n"]))
    assert got == [0, 1, 2]


@pytest.mark.parametrize("factory", EVENT_BUS_FACTORIES)
async def test_event_bus_two_groups_see_same_messages(
    factory: Callable[[], EventBus],
) -> None:
    bus = factory()
    await bus.publish("aw.change.events", "k", {"n": 1})
    await bus.publish("aw.change.events", "k", {"n": 2})

    a: list[int] = []
    async for e in bus.subscribe("aw.change.events", "group-a"):
        a.append(int(e.payload["n"]))
    b: list[int] = []
    async for e in bus.subscribe("aw.change.events", "group-b"):
        b.append(int(e.payload["n"]))
    assert a == [1, 2]
    assert b == [1, 2]


@pytest.mark.parametrize("factory", EVENT_BUS_FACTORIES)
async def test_event_bus_same_group_resumes_from_committed_offset(
    factory: Callable[[], EventBus],
) -> None:
    bus = factory()
    await bus.publish("aw.change.events", "k", {"n": 1})
    await bus.publish("aw.change.events", "k", {"n": 2})

    first_pass: list[int] = []
    async for e in bus.subscribe("aw.change.events", "group-a"):
        first_pass.append(int(e.payload["n"]))
    assert first_pass == [1, 2]

    second_pass: list[int] = []
    async for e in bus.subscribe("aw.change.events", "group-a"):
        second_pass.append(int(e.payload["n"]))
    assert second_pass == []

    await bus.publish("aw.change.events", "k", {"n": 3})
    third_pass: list[int] = []
    async for e in bus.subscribe("aw.change.events", "group-a"):
        third_pass.append(int(e.payload["n"]))
    assert third_pass == [3]


@pytest.mark.parametrize("factory", EVENT_BUS_FACTORIES)
async def test_event_bus_dead_letter_uses_topic_dlq_convention(
    factory: Callable[[], EventBus],
) -> None:
    bus = factory()
    await bus.publish("aw.change.events", "k", {"n": 1})
    await bus.dead_letter("aw.change.events", "k", {"n": 1}, reason="poison")

    envelopes = []
    async for e in bus.subscribe("aw.change.events.dlq", "auditor"):
        envelopes.append(e)
    assert len(envelopes) == 1
    assert envelopes[0].topic == "aw.change.events.dlq"
    assert envelopes[0].payload["original_topic"] == "aw.change.events"
    assert envelopes[0].payload["reason"] == "poison"


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
