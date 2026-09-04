"""Delivery-side activation of a locally saved Teams Workflows endpoint.

A local profile stores the Teams endpoint only as ciphertext in the
Operator-owned loopback database. This module is the Core-side reader for that
same record, so a local deployment can activate A2/A4 delivery without copying
the endpoint into a plaintext file or environment variable.

Activation is explicit and separate from saving: `FDAI_TEAMS_NOTIFICATION_ACTIVATION`
opts a local deployment in, and the record is used only when it decrypts, passes
its own digest check, and came through the Operator's strict Teams Workflow URL
validation. A saved-but-not-activated record resolves to `None`, which leaves
the binding excluded from every target set.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from fdai_service_contracts.notification_binding import (
    LOCAL_TEAMS_BINDING_STATE_KEY,
    LocalTeamsBindingRecordError,
    decode_local_binding_record,
    local_binding_key_material,
)

ACTIVATION_ENV: Final[str] = "FDAI_TEAMS_NOTIFICATION_ACTIVATION"
DEFAULT_LOCAL_ENDPOINT_ENV: Final[str] = "FDAI_TEAMS_OPS_ENDPOINT"
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_LOGGER = logging.getLogger("fdai.startup")


class LocalBindingStateReader(Protocol):
    """Read one durable local state record by key."""

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class LocalEncryptedNotificationBindingStore:
    """Resolve the activated local Teams endpoint without exposing it elsewhere."""

    state_store: LocalBindingStateReader
    key_material: str = field(repr=False)

    async def load_endpoint(self) -> str | None:
        """Return the saved endpoint, or ``None`` when no usable record exists."""
        record = await self.state_store.read_state(LOCAL_TEAMS_BINDING_STATE_KEY)
        try:
            decoded = decode_local_binding_record(record, key_material=self.key_material)
        except LocalTeamsBindingRecordError:
            _LOGGER.warning("local_teams_binding_unusable", extra={"reason": "record_invalid"})
            return None
        if decoded is None:
            return None
        endpoint, _version = decoded
        return endpoint


def notification_activation_requested(environment: Mapping[str, str]) -> bool:
    """Report whether a deployment explicitly activated Teams notification delivery."""
    return environment.get(ACTIVATION_ENV, "").strip().casefold() in _TRUTHY


async def resolve_local_notification_endpoints(
    *,
    environment: Mapping[str, str],
    state_store: LocalBindingStateReader | None,
    key_material: str | None,
) -> dict[str, str]:
    """Build endpoint overrides for an activated local Teams binding.

    Returns an empty mapping when activation was not requested, when the local
    record is missing or unusable, or when the environment already supplies the
    endpoint. Saving a binding never reaches this function, so a save can never
    enable a destination on its own.
    """
    if not notification_activation_requested(environment):
        return {}
    if state_store is None or not key_material:
        return {}
    if environment.get(DEFAULT_LOCAL_ENDPOINT_ENV, "").strip():
        return {}
    endpoint = await LocalEncryptedNotificationBindingStore(
        state_store=state_store,
        key_material=local_binding_key_material(key_material),
    ).load_endpoint()
    if endpoint is None:
        _LOGGER.info(
            "teams_notification_activation_pending",
            extra={"reason": "no_saved_local_binding"},
        )
        return {}
    return {DEFAULT_LOCAL_ENDPOINT_ENV: endpoint}


__all__ = [
    "ACTIVATION_ENV",
    "DEFAULT_LOCAL_ENDPOINT_ENV",
    "LocalBindingStateReader",
    "LocalEncryptedNotificationBindingStore",
    "notification_activation_requested",
    "resolve_local_notification_endpoints",
]
