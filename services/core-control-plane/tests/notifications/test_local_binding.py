"""Explicit local activation of the encrypted Operator-owned Teams binding."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import pytest
from fdai.delivery.notifications.local_binding import (
    ACTIVATION_ENV,
    DEFAULT_LOCAL_ENDPOINT_ENV,
    notification_activation_requested,
    resolve_local_notification_endpoints,
)
from fdai_service_contracts.notification_binding import (
    LOCAL_TEAMS_BINDING_STATE_KEY,
    encode_local_binding_record,
    local_binding_cipher,
    local_binding_key_material,
)

DSN = "postgresql://user:secret@localhost:5432/fdai"
OPERATOR_DSN = f"{DSN}?options=-c%20role%3Dfdai_operator_api"
ENDPOINT = "https://example.environment.api.powerplatform.com/trigger"


class MemoryStateStore:
    def __init__(self, record: Mapping[str, object] | None = None) -> None:
        self.records: dict[str, dict[str, object]] = {}
        if record is not None:
            self.records[LOCAL_TEAMS_BINDING_STATE_KEY] = dict(record)

    async def read_state(self, key: str) -> dict[str, object] | None:
        stored = self.records.get(key)
        return dict(stored) if stored is not None else None


def _saved_record(*, key_material: str = OPERATOR_DSN) -> dict[str, object]:
    cipher = local_binding_cipher(local_binding_key_material(key_material))
    return encode_local_binding_record(
        version="version-1",
        endpoint_digest=hashlib.sha256(ENDPOINT.encode("utf-8")).hexdigest(),
        ciphertext=cipher.encrypt(ENDPOINT.encode("utf-8")).decode("ascii"),
    )


def test_role_scoped_dsns_derive_one_shared_key_material() -> None:
    assert local_binding_key_material(OPERATOR_DSN) == local_binding_key_material(DSN)


async def test_saving_without_activation_never_enables_a_destination() -> None:
    store = MemoryStateStore(_saved_record())

    overrides = await resolve_local_notification_endpoints(
        environment={},
        state_store=store,
        key_material=DSN,
    )

    assert overrides == {}
    assert notification_activation_requested({}) is False


async def test_explicit_activation_resolves_the_operator_saved_endpoint() -> None:
    store = MemoryStateStore(_saved_record())

    overrides = await resolve_local_notification_endpoints(
        environment={ACTIVATION_ENV: "1"},
        state_store=store,
        key_material=DSN,
    )

    assert overrides == {DEFAULT_LOCAL_ENDPOINT_ENV: ENDPOINT}


async def test_activation_without_a_saved_record_stays_inactive() -> None:
    overrides = await resolve_local_notification_endpoints(
        environment={ACTIVATION_ENV: "true"},
        state_store=MemoryStateStore(),
        key_material=DSN,
    )

    assert overrides == {}


async def test_an_undecryptable_record_degrades_instead_of_failing_startup() -> None:
    store = MemoryStateStore(_saved_record(key_material="postgresql://other/host"))

    overrides = await resolve_local_notification_endpoints(
        environment={ACTIVATION_ENV: "yes"},
        state_store=store,
        key_material=DSN,
    )

    assert overrides == {}


async def test_an_explicit_environment_endpoint_wins_over_the_local_record() -> None:
    store = MemoryStateStore(_saved_record())

    overrides = await resolve_local_notification_endpoints(
        environment={
            ACTIVATION_ENV: "on",
            DEFAULT_LOCAL_ENDPOINT_ENV: "https://deployment.example.com/trigger",
        },
        state_store=store,
        key_material=DSN,
    )

    assert overrides == {}


async def test_explicit_activation_fails_closed_when_the_state_store_is_unavailable() -> None:
    class FailingStore:
        async def read_state(self, key: str) -> dict[str, object] | None:
            raise RuntimeError("local store unavailable")

    with pytest.raises(RuntimeError, match="local store unavailable"):
        await resolve_local_notification_endpoints(
            environment={ACTIVATION_ENV: "1"},
            state_store=FailingStore(),
            key_material=DSN,
        )
