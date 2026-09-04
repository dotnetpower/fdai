"""Compose send-only notification channels from named bindings.

Extracted from the delivery composition root so binding resolution, endpoint
placeholder refusal, and adapter construction have one reason to change.

`endpoint_overrides` carries values a local deployment activated from the
encrypted Operator-owned record instead of a plaintext environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any, cast

import httpx

from fdai.core.notifications.router import ChannelBinding, ChannelRegistry
from fdai.delivery.integration_readiness import endpoint_is_placeholder
from fdai.shared.providers.notifications import NotificationChannel

_LOGGER = logging.getLogger("fdai.startup")
_ACS_SCOPE = "https://communication.azure.com/.default"
_TEAMS_WORKFLOW_SCOPE = "https://service.flow.microsoft.com/.default"


def _build_notification_registry(
    http_client: httpx.AsyncClient | None,
    endpoint_overrides: Mapping[str, str] | None = None,
) -> Any:
    """Bind configured send-only notification adapters.

    ``endpoint_overrides`` carries endpoint values a local deployment activated
    from the encrypted Operator-owned record instead of a plaintext environment
    variable. It never widens the binding set: only bindings that already
    declare that environment name can resolve through it.
    """
    overrides = dict(endpoint_overrides or {})
    resolved_env: Mapping[str, str] = {**os.environ, **overrides}
    bindings_raw = os.environ.get("FDAI_NOTIFICATION_BINDINGS_JSON", "").strip()
    if bindings_raw:
        if http_client is None:
            raise RuntimeError(
                "FDAI_NOTIFICATION_BINDINGS_JSON is set but no HTTP client is available"
            )
        return _build_named_notification_registry(bindings_raw, http_client, overrides)

    registry = ChannelRegistry()
    from fdai.delivery.notifications import default_notification_bindings_from_env

    implicit_bindings_raw = default_notification_bindings_from_env(resolved_env)
    if implicit_bindings_raw:
        if http_client is None:
            raise RuntimeError(
                "a Teams or Slack notification webhook URL is set but no HTTP client is available"
            )
        _LOGGER.info("notification_bindings_defaulted")
        registry = _build_named_notification_registry(
            implicit_bindings_raw,
            http_client,
            overrides,
        )

    endpoint = os.environ.get("FDAI_EMAIL_ENDPOINT", "").strip()
    if not endpoint:
        return registry
    if http_client is None:
        raise RuntimeError(
            "FDAI_EMAIL_ENDPOINT is set but no HTTP client is available. "
            "The composition root MUST create an httpx.AsyncClient before "
            "building notification channels."
        )

    sender_address = os.environ.get("FDAI_EMAIL_SENDER_ADDRESS", "").strip()
    recipients_raw = os.environ.get("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON", "").strip()
    identity_client_id = os.environ.get("FDAI_NOTIFICATION_MI_CLIENT_ID", "").strip()
    if not sender_address or not recipients_raw or not identity_client_id:
        raise RuntimeError(
            "FDAI_EMAIL_ENDPOINT requires FDAI_EMAIL_SENDER_ADDRESS, "
            "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON, and FDAI_NOTIFICATION_MI_CLIENT_ID"
        )
    try:
        recipients_value = json.loads(recipients_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON is not valid JSON") from exc
    if (
        not isinstance(recipients_value, list)
        or not recipients_value
        or not all(isinstance(address, str) and address.strip() for address in recipients_value)
    ):
        raise RuntimeError("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON MUST be a non-empty string array")
    recipients = tuple(dict.fromkeys(address.strip() for address in recipients_value))

    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
    from fdai.delivery.notifications import (
        AzureCommunicationEmailChannel,
        AzureCommunicationEmailConfig,
    )

    identity = ManagedIdentityWorkloadIdentity.from_env(
        http_client=http_client,
        client_id_env="FDAI_NOTIFICATION_MI_CLIENT_ID",
    )

    async def token_provider() -> str:
        return (await identity.get_token(_ACS_SCOPE)).token

    channels: dict[str, NotificationChannel] = {}
    for channel_id in ("email-oncall", "email-governance"):
        channel = AzureCommunicationEmailChannel(
            config=AzureCommunicationEmailConfig(
                channel_id=channel_id,
                endpoint=endpoint,
                sender_address=sender_address,
                recipient_addresses=recipients,
            ),
            http_client=http_client,
            token_provider=token_provider,
        )
        channels[channel_id] = cast(NotificationChannel, channel)
    _LOGGER.info(
        "notification_email_backend",
        extra={"backend": "acs-email", "channel_count": len(channels)},
    )
    bindings = {
        channel_id: ChannelBinding(
            channel_id=channel_id,
            trust_tiers=channel.trust_tiers,
        )
        for channel_id, channel in channels.items()
    }
    return ChannelRegistry(
        channels={**registry.channels, **channels},
        bindings={**registry.bindings, **bindings},
    )


def _build_named_notification_registry(
    raw: str,
    http_client: httpx.AsyncClient,
    endpoint_overrides: Mapping[str, str] | None = None,
) -> ChannelRegistry:
    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
    from fdai.delivery.notifications import (
        AzureCommunicationEmailChannel,
        AzureCommunicationEmailConfig,
        NotificationBindingKind,
        SlackWebhookChannel,
        SlackWebhookConfig,
        TeamsWebhookChannel,
        TeamsWebhookConfig,
        TeamsWorkflowAuthMode,
        parse_notification_bindings,
    )

    try:
        specs = parse_notification_bindings(raw)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    identities: dict[str, ManagedIdentityWorkloadIdentity] = {}

    def identity_for(env_name: str) -> ManagedIdentityWorkloadIdentity:
        identity = identities.get(env_name)
        if identity is None:
            identity = ManagedIdentityWorkloadIdentity.from_env(
                http_client=http_client,
                client_id_env=env_name,
            )
            identities[env_name] = identity
        return identity

    channels: dict[str, NotificationChannel] = {}
    bindings: dict[str, ChannelBinding] = {}
    for spec in specs:
        bindings[spec.channel_id] = ChannelBinding(
            channel_id=spec.channel_id,
            enabled=spec.enabled,
            configured=not spec.enabled,
            trust_tiers=spec.trust_tiers,
        )
        if not spec.enabled:
            continue
        if spec.endpoint_env is None:
            raise RuntimeError(
                f"enabled notification binding {spec.channel_id!r} has no endpoint reference"
            )
        endpoint = _required_notification_env(
            spec.channel_id,
            spec.endpoint_env,
            endpoint_overrides,
            is_endpoint_url=True,
        )
        if spec.kind is NotificationBindingKind.TEAMS_WORKFLOW:
            auth_mode = spec.auth_mode
            if auth_mode is None:
                raise RuntimeError(f"enabled Teams binding {spec.channel_id!r} has no auth mode")
            token_provider = None
            if auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY:
                identity = identity_for(spec.identity_client_id_env)

                async def teams_token_provider(
                    selected: ManagedIdentityWorkloadIdentity = identity,
                ) -> str:
                    return (await selected.get_token(_TEAMS_WORKFLOW_SCOPE)).token

                token_provider = teams_token_provider
            channel: NotificationChannel = cast(
                NotificationChannel,
                TeamsWebhookChannel(
                    config=TeamsWebhookConfig(
                        channel_id=spec.channel_id,
                        webhook_url=endpoint,
                        trust_tiers=spec.trust_tiers,
                        auth_mode=auth_mode,
                    ),
                    http_client=http_client,
                    token_provider=token_provider,
                ),
            )
        elif spec.kind is NotificationBindingKind.SLACK_WEBHOOK:
            channel = cast(
                NotificationChannel,
                SlackWebhookChannel(
                    config=SlackWebhookConfig(
                        channel_id=spec.channel_id,
                        webhook_url=endpoint,
                        trust_tiers=spec.trust_tiers,
                    ),
                    http_client=http_client,
                ),
            )
        else:
            if spec.sender_address_env is None or spec.recipient_addresses_env is None:
                raise RuntimeError(f"enabled email binding {spec.channel_id!r} is incomplete")
            sender = _required_notification_env(spec.channel_id, spec.sender_address_env)
            recipients = _notification_recipients(
                spec.channel_id,
                _required_notification_env(spec.channel_id, spec.recipient_addresses_env),
            )
            identity = identity_for(spec.identity_client_id_env)

            async def email_token_provider(
                selected: ManagedIdentityWorkloadIdentity = identity,
            ) -> str:
                return (await selected.get_token(_ACS_SCOPE)).token

            channel = cast(
                NotificationChannel,
                AzureCommunicationEmailChannel(
                    config=AzureCommunicationEmailConfig(
                        channel_id=spec.channel_id,
                        endpoint=endpoint,
                        sender_address=sender,
                        recipient_addresses=recipients,
                        trust_tiers=spec.trust_tiers,
                    ),
                    http_client=http_client,
                    token_provider=email_token_provider,
                ),
            )
        channels[spec.channel_id] = channel
        bindings[spec.channel_id] = ChannelBinding(
            channel_id=spec.channel_id,
            enabled=True,
            configured=True,
            trust_tiers=spec.trust_tiers,
        )

    _LOGGER.info(
        "notification_bindings",
        extra={
            "binding_count": len(bindings),
            "enabled_count": len(channels),
        },
    )
    return ChannelRegistry(channels=channels, bindings=bindings)


def _required_notification_env(
    channel_id: str,
    env_name: str,
    endpoint_overrides: Mapping[str, str] | None = None,
    *,
    is_endpoint_url: bool = False,
) -> str:
    """Resolve one binding value, refusing an unconfigured deployment placeholder.

    Terraform seeds the endpoint secret before an Owner saves a real URL. That
    placeholder MUST NOT activate a destination, so an enabled binding whose
    endpoint still resolves to it fails startup instead of silently reaching
    nobody. Non-URL values such as a sender address are not URL-shaped and are
    only checked for presence.
    """
    overrides = endpoint_overrides or {}
    value = (overrides.get(env_name) or os.environ.get(env_name, "")).strip()
    if not value:
        raise RuntimeError(
            f"enabled notification binding {channel_id!r} requires environment variable {env_name}"
        )
    if is_endpoint_url and endpoint_is_placeholder(value):
        raise RuntimeError(
            f"enabled notification binding {channel_id!r} still resolves to the unconfigured "
            f"{env_name} placeholder; save a real endpoint before activating delivery"
        )
    return value


def _notification_recipients(channel_id: str, raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"notification binding {channel_id!r} recipient environment value is invalid JSON"
        ) from exc
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise RuntimeError(
            f"notification binding {channel_id!r} recipients MUST be a non-empty string array"
        )
    return tuple(dict.fromkeys(item.strip() for item in value))


def build_notification_delivery_store() -> Any:
    """Select the durable per-channel notification delivery store for this process.

    The durable store is used whenever ``FDAI_STATE_STORE_DSN`` is configured so
    dispatch and publication-receipt observation converge on one record. The
    in-memory fallback keeps a DSN-free local process runnable and is
    process-scoped by construction, so it MUST be shared by every caller in one
    process rather than rebuilt per component.
    """
    from fdai.core.notifications import InMemoryNotificationDeliveryStore

    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return InMemoryNotificationDeliveryStore()
    from fdai.delivery.persistence import (
        PostgresNotificationDeliveryStore,
        PostgresStateStoreConfig,
    )

    return PostgresNotificationDeliveryStore(config=PostgresStateStoreConfig(dsn=dsn))


__all__ = [
    "build_notification_delivery_store",
]
