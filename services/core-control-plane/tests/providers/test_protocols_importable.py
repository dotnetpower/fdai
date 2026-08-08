"""Structural checks for the four provider Protocols.

Verifies:
1. The shipped in-memory fakes satisfy each Protocol structurally (so a
   ``isinstance(fake, EventBus)`` runtime check succeeds - mypy handles
   the static side).
2. Every Protocol is importable from ``fdai.shared.providers``.

Behavioural tests (publish → subscribe round-trip, audit chain integrity,
etc.) live in :mod:`tests.providers.test_contracts` so a future
Postgres / Redpanda adapter re-runs the *same* test file against the real
backend.
"""

from __future__ import annotations

from fdai.shared.providers import (
    EventBus,
    SecretProvider,
    StateStore,
    WorkloadIdentity,
)
from fdai.shared.providers.testing import (
    InMemoryEventBus,
    InMemorySecretProvider,
    InMemoryStateStore,
    StaticWorkloadIdentity,
)


def test_state_store_protocol_is_structural() -> None:
    fake = InMemoryStateStore()
    assert isinstance(fake, StateStore)


def test_event_bus_protocol_is_structural() -> None:
    fake = InMemoryEventBus()
    assert isinstance(fake, EventBus)


def test_secret_provider_protocol_is_structural() -> None:
    fake = InMemorySecretProvider({"kv/example": "value"})
    assert isinstance(fake, SecretProvider)


def test_workload_identity_protocol_is_structural() -> None:
    fake = StaticWorkloadIdentity(audience="https://kafka.example")
    assert isinstance(fake, WorkloadIdentity)
