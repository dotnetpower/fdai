"""Strict named notification binding configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai.shared.providers.notifications import ChannelMode, TrustTier, require_channel_id

from .teams import TeamsWorkflowAuthMode

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_MAX_BINDINGS = 64
NOTIFICATION_TRUST_TIERS: frozenset[TrustTier] = frozenset(
    {TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST}
)
"""Tiers an outbound-only `NotificationChannel` binding may declare.

A1 approvals need a verified approver and an action-bound callback, and A3
conversations need a bidirectional adapter. Neither can be satisfied by a
send-only webhook or mailbox, so a binding that claims them is a configuration
defect rather than a widened audience.
"""


class NotificationBindingKind(StrEnum):
    TEAMS_WORKFLOW = "teams_workflow"
    SLACK_WEBHOOK = "slack_webhook"
    ACS_EMAIL = "acs_email"
    DIRECT_LINE = "direct_line"


@dataclass(frozen=True, slots=True)
class NotificationBindingSpec:
    channel_id: str
    kind: NotificationBindingKind
    enabled: bool
    trust_tiers: frozenset[TrustTier]
    mode: ChannelMode = ChannelMode.ENFORCE
    endpoint_env: str | None = None
    auth_mode: TeamsWorkflowAuthMode | None = None
    sender_address_env: str | None = None
    recipient_addresses_env: str | None = None
    identity_client_id_env: str = "FDAI_NOTIFICATION_MI_CLIENT_ID"
    conversation_id_env: str | None = None
    secret_env: str | None = None


def default_notification_bindings_from_env(environment: Mapping[str, str]) -> str:
    """Build default matrix bindings from URL-only webhook configuration."""
    bindings: dict[str, dict[str, object]] = {}
    if environment.get("FDAI_TEAMS_OPS_ENDPOINT", "").strip():
        bindings["teams-ops-prd"] = {
            "kind": "teams_workflow",
            "enabled": True,
            "mode": "enforce",
            "trust_tiers": ["a2_operational_alert"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
        }
        bindings["teams-hil-prd"] = {
            "kind": "teams_workflow",
            "enabled": True,
            "mode": "enforce",
            "trust_tiers": ["a4_digest"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
        }
    if environment.get("FDAI_SLACK_OPS_WEBHOOK_URL", "").strip():
        bindings["slack-ops-prd"] = {
            "kind": "slack_webhook",
            "enabled": True,
            "mode": "enforce",
            "trust_tiers": ["a2_operational_alert"],
            "endpoint_env": "FDAI_SLACK_OPS_WEBHOOK_URL",
        }
    return json.dumps(bindings, separators=(",", ":")) if bindings else ""


def parse_notification_bindings(raw: str) -> tuple[NotificationBindingSpec, ...]:
    """Parse a channel-id keyed JSON object without resolving secret values."""
    try:
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise ValueError("FDAI_NOTIFICATION_BINDINGS_JSON is not valid JSON") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError("FDAI_NOTIFICATION_BINDINGS_JSON MUST be a non-empty object")
    if len(value) > _MAX_BINDINGS:
        raise ValueError(
            f"FDAI_NOTIFICATION_BINDINGS_JSON MUST contain at most {_MAX_BINDINGS} bindings"
        )
    return tuple(_parse_binding(channel_id, spec) for channel_id, spec in value.items())


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"notification binding JSON has duplicate key {key!r}")
        value[key] = item
    return value


def _parse_binding(channel_id: object, raw: object) -> NotificationBindingSpec:
    if not isinstance(channel_id, str):
        raise ValueError("notification binding id MUST be a string")
    require_channel_id(channel_id)
    if not isinstance(raw, dict):
        raise ValueError(f"notification binding {channel_id!r} MUST be an object")
    allowed = {
        "kind",
        "enabled",
        "mode",
        "trust_tiers",
        "endpoint_env",
        "auth_mode",
        "sender_address_env",
        "recipient_addresses_env",
        "identity_client_id_env",
        "conversation_id_env",
        "secret_env",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"notification binding {channel_id!r} has unknown keys {unknown!r}")
    kind = _enum_value(raw, "kind", NotificationBindingKind, channel_id)
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError(f"notification binding {channel_id!r} 'enabled' MUST be boolean")
    # Direct Line is a new capability, so an omitted mode stays in shadow; the
    # older kinds keep their backward-compatible enforce default.
    default_mode = (
        ChannelMode.SHADOW if kind is NotificationBindingKind.DIRECT_LINE else ChannelMode.ENFORCE
    )
    mode = _enum_value(raw, "mode", ChannelMode, channel_id) if "mode" in raw else default_mode
    trust_tiers = _trust_tiers(channel_id, raw.get("trust_tiers"))
    if kind is NotificationBindingKind.DIRECT_LINE:
        return _direct_line_binding(channel_id, raw, enabled, mode, trust_tiers)
    _reject_fields(channel_id, raw, {"conversation_id_env", "secret_env"})
    identity_env = _env_name(
        raw.get("identity_client_id_env", "FDAI_NOTIFICATION_MI_CLIENT_ID"),
        channel_id,
        "identity_client_id_env",
    )

    if kind is NotificationBindingKind.TEAMS_WORKFLOW:
        _reject_fields(channel_id, raw, {"sender_address_env", "recipient_addresses_env"})
        auth_mode = None
        if "auth_mode" in raw:
            auth_mode = _enum_value(raw, "auth_mode", TeamsWorkflowAuthMode, channel_id)
        elif enabled and mode is ChannelMode.ENFORCE:
            raise ValueError(
                f"enabled enforce notification binding {channel_id!r} requires 'auth_mode'"
            )
        endpoint_env = _optional_env_name(raw.get("endpoint_env"), channel_id, "endpoint_env")
        if enabled and mode is ChannelMode.ENFORCE and endpoint_env is None:
            raise ValueError(
                f"enabled enforce notification binding {channel_id!r} requires 'endpoint_env'"
            )
        return NotificationBindingSpec(
            channel_id=channel_id,
            kind=kind,
            enabled=enabled,
            trust_tiers=trust_tiers,
            mode=mode,
            endpoint_env=endpoint_env,
            auth_mode=auth_mode,
            identity_client_id_env=identity_env,
        )

    if kind is NotificationBindingKind.SLACK_WEBHOOK:
        _reject_fields(
            channel_id,
            raw,
            {
                "auth_mode",
                "sender_address_env",
                "recipient_addresses_env",
                "identity_client_id_env",
            },
        )
        endpoint_env = _optional_env_name(raw.get("endpoint_env"), channel_id, "endpoint_env")
        if enabled and mode is ChannelMode.ENFORCE and endpoint_env is None:
            raise ValueError(
                f"enabled enforce notification binding {channel_id!r} requires 'endpoint_env'"
            )
        return NotificationBindingSpec(
            channel_id=channel_id,
            kind=kind,
            enabled=enabled,
            trust_tiers=trust_tiers,
            mode=mode,
            endpoint_env=endpoint_env,
        )

    if mode is ChannelMode.SHADOW:
        raise ValueError("acs_email notification bindings do not support shadow mode")
    _reject_fields(channel_id, raw, {"auth_mode"})
    endpoint_env = _optional_env_name(raw.get("endpoint_env"), channel_id, "endpoint_env")
    sender_env = _optional_env_name(
        raw.get("sender_address_env"),
        channel_id,
        "sender_address_env",
    )
    recipients_env = _optional_env_name(
        raw.get("recipient_addresses_env"),
        channel_id,
        "recipient_addresses_env",
    )
    if enabled and None in {endpoint_env, sender_env, recipients_env}:
        raise ValueError(
            f"enabled notification binding {channel_id!r} requires endpoint, sender, "
            "and recipient environment references"
        )
    return NotificationBindingSpec(
        channel_id=channel_id,
        kind=kind,
        enabled=enabled,
        trust_tiers=trust_tiers,
        mode=mode,
        endpoint_env=endpoint_env,
        sender_address_env=sender_env,
        recipient_addresses_env=recipients_env,
        identity_client_id_env=identity_env,
    )


def _direct_line_binding(
    channel_id: str,
    raw: Mapping[str, Any],
    enabled: bool,
    mode: ChannelMode,
    trust_tiers: frozenset[TrustTier],
) -> NotificationBindingSpec:
    """Parse one Direct Line custom-channel binding without resolving its values.

    Rehearsal (shadow) needs no reference. An enabled enforce binding names
    three distinct environment variables for the endpoint, conversation id, and
    secret so one protected value can never be reused as another.
    """
    _reject_fields(
        channel_id,
        raw,
        {"auth_mode", "sender_address_env", "recipient_addresses_env", "identity_client_id_env"},
    )
    endpoint_env = _optional_env_name(raw.get("endpoint_env"), channel_id, "endpoint_env")
    conversation_env = _optional_env_name(
        raw.get("conversation_id_env"), channel_id, "conversation_id_env"
    )
    secret_env = _optional_env_name(raw.get("secret_env"), channel_id, "secret_env")
    references = [name for name in (endpoint_env, conversation_env, secret_env) if name]
    if len(references) != len(set(references)):
        raise ValueError(
            f"notification binding {channel_id!r} MUST use distinct environment references"
        )
    if enabled and mode is ChannelMode.ENFORCE and len(references) != 3:
        raise ValueError(
            f"enabled enforce notification binding {channel_id!r} requires endpoint, "
            "conversation, and secret environment references"
        )
    return NotificationBindingSpec(
        channel_id=channel_id,
        kind=NotificationBindingKind.DIRECT_LINE,
        enabled=enabled,
        trust_tiers=trust_tiers,
        mode=mode,
        endpoint_env=endpoint_env,
        conversation_id_env=conversation_env,
        secret_env=secret_env,
    )


def _trust_tiers(channel_id: str, raw: object) -> frozenset[TrustTier]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"notification binding {channel_id!r} 'trust_tiers' MUST be a non-empty array"
        )
    parsed: set[TrustTier] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"notification binding {channel_id!r} trust tiers MUST be strings")
        try:
            parsed.add(TrustTier(item))
        except ValueError as exc:
            raise ValueError(
                f"notification binding {channel_id!r} has unknown trust tier {item!r}"
            ) from exc
    refused = sorted(tier.value for tier in parsed - NOTIFICATION_TRUST_TIERS)
    if refused:
        raise ValueError(
            f"notification binding {channel_id!r} MUST NOT declare trust tiers {refused!r}; "
            "send-only notification bindings carry a2_operational_alert or a4_digest only"
        )
    return frozenset(parsed)


def _enum_value(
    raw: Mapping[str, Any],
    field: str,
    enum_type: type[StrEnum],
    channel_id: str,
) -> Any:
    value = raw.get(field)
    if not isinstance(value, str):
        raise ValueError(f"notification binding {channel_id!r} {field!r} MUST be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(
            f"notification binding {channel_id!r} has unknown {field} {value!r}"
        ) from exc


def _reject_fields(channel_id: str, raw: Mapping[str, Any], fields: set[str]) -> None:
    present = sorted(fields.intersection(raw))
    if present:
        raise ValueError(f"notification binding {channel_id!r} does not support fields {present!r}")


def _optional_env_name(value: object, channel_id: str, field: str) -> str | None:
    if value is None:
        return None
    return _env_name(value, channel_id, field)


def _env_name(value: object, channel_id: str, field: str) -> str:
    if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
        raise ValueError(
            f"notification binding {channel_id!r} {field!r} MUST name an environment variable"
        )
    return value


__all__ = [
    "NOTIFICATION_TRUST_TIERS",
    "NotificationBindingKind",
    "NotificationBindingSpec",
    "default_notification_bindings_from_env",
    "parse_notification_bindings",
]
