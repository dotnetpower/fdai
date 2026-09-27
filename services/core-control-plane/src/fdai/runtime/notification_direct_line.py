"""Compose Bot Framework Direct Line custom-channel notification adapters.

Kept apart from :mod:`fdai.runtime.notification_registry` so the Direct Line
rehearsal-to-governed-delivery rules have one reason to change:

- ``mode: shadow`` (the Direct Line default) registers a
  :class:`~fdai.core.notifications.shadow.ShadowNotificationChannel` that renders
  the exact activity, records it durably, and never resolves a protected value
  or constructs a transport.
- ``mode: enforce`` resolves the endpoint, conversation id, and secret from
  protected configuration and fails startup when any is missing, still a
  seeded placeholder, or structurally invalid. A governed channel is also
  refused on a failover route, because only fan-out persists the per-channel
  delivery record before transport.

No resolved value is logged, returned, or echoed in an error.
"""

from __future__ import annotations

from typing import Protocol, cast

import httpx

from fdai.core.notifications.matrix import DeliveryMode, NotificationMatrix
from fdai.core.notifications.router import ChannelRegistry
from fdai.core.notifications.shadow import ShadowDeliveryRecorder, ShadowNotificationChannel
from fdai.delivery.integration_readiness import value_is_placeholder
from fdai.delivery.notifications import (
    DirectLineConfig,
    DirectLineNotificationChannel,
    NotificationBindingKind,
    NotificationBindingSpec,
    render_direct_line_payload,
    static_direct_line_credential,
)
from fdai.shared.providers.notifications import ChannelKind, ChannelMode, NotificationChannel


class ProtectedValueResolver(Protocol):
    """Resolve one binding environment reference or raise :class:`RuntimeError`."""

    def __call__(self, env_name: str, /, *, is_endpoint_url: bool = False) -> str: ...


def build_direct_line_channel(
    spec: NotificationBindingSpec,
    *,
    http_client: httpx.AsyncClient | None,
    shadow_recorder: ShadowDeliveryRecorder,
    resolve: ProtectedValueResolver,
) -> NotificationChannel:
    """Return the rehearsal or governed adapter for one enabled Direct Line binding."""

    if spec.kind is not NotificationBindingKind.DIRECT_LINE or not spec.enabled:
        raise RuntimeError(
            f"notification binding {spec.channel_id!r} is not an enabled Direct Line"
        )
    if spec.mode is ChannelMode.SHADOW:
        return cast(
            NotificationChannel,
            ShadowNotificationChannel(
                channel_kind=ChannelKind.DIRECT_LINE,
                channel_id=spec.channel_id,
                trust_tiers=spec.trust_tiers,
                recorder=shadow_recorder,
                payload_renderer=render_direct_line_payload,
            ),
        )
    if http_client is None:
        raise RuntimeError(
            f"enabled enforce notification binding {spec.channel_id!r} requires an HTTP client"
        )
    if spec.endpoint_env is None or spec.conversation_id_env is None or spec.secret_env is None:
        raise RuntimeError(f"enabled Direct Line binding {spec.channel_id!r} is incomplete")
    endpoint = resolve(spec.endpoint_env, is_endpoint_url=True)
    conversation_id = _protected_value(spec.channel_id, spec.conversation_id_env, resolve)
    secret = _protected_value(spec.channel_id, spec.secret_env, resolve)
    try:
        channel = DirectLineNotificationChannel(
            config=DirectLineConfig(
                channel_id=spec.channel_id,
                endpoint=endpoint,
                conversation_id=conversation_id,
                trust_tiers=spec.trust_tiers,
            ),
            http_client=http_client,
            credential_provider=static_direct_line_credential(secret),
        )
    except ValueError as exc:
        raise RuntimeError(
            f"enabled Direct Line binding {spec.channel_id!r} is invalid: {exc}"
        ) from exc
    return cast(NotificationChannel, channel)


def require_fanout_for_governed_direct_line(
    matrix: NotificationMatrix,
    registry: ChannelRegistry,
) -> None:
    """Fail startup when a governed Direct Line channel sits on a failover route.

    Only fan-out routes persist the per-channel delivery record before
    transport, so governed Direct Line delivery is refused anywhere else. A
    rehearsal channel sends nothing and may appear on any route.
    """

    for route in matrix.routes.values():
        if route.delivery_mode is DeliveryMode.FANOUT:
            continue
        governed = [
            channel_id
            for channel_id in route.channel_ids
            if isinstance(registry.resolve(channel_id), DirectLineNotificationChannel)
        ]
        if governed:
            raise RuntimeError(
                f"route {route.category!r} uses failover delivery for governed Direct Line "
                f"channels {governed!r}; declare delivery_mode: fanout so the per-channel "
                "intent is recorded before transport"
            )


def _protected_value(channel_id: str, env_name: str, resolve: ProtectedValueResolver) -> str:
    value = resolve(env_name)
    if value_is_placeholder(value):
        raise RuntimeError(
            f"enabled notification binding {channel_id!r} still resolves to the unconfigured "
            f"{env_name} placeholder; save a real value before activating delivery"
        )
    return value


__all__ = [
    "ProtectedValueResolver",
    "build_direct_line_channel",
    "require_fanout_for_governed_direct_line",
]
