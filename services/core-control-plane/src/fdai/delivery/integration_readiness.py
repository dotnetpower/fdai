"""Source-attributed integration readiness rows for the Settings projection.

Readiness here means *configuration completeness observed in one runtime*, never
provider health. A row is `ready` only when every prerequisite this process can
actually observe is present; a provider outage still surfaces as a failed
delivery, not as a readiness change (see
`docs/roadmap/interfaces/multi-channel-notification-delivery.md`).

Each row carries the `source` runtime that owns its prerequisites so an operator
can act on the right surface, and `observed` states whether this process could
see that source at all. A projection produced by the Core control plane cannot
observe Operator-only Teams inputs, so those rows report `observed: false`
rather than claiming "not configured".

The four Teams-facing categories stay distinct because they have different
transports, different trust, and different failure meanings:

* `teams-a1-approval-send` - Core Bot delivery of an approval card.
* `teams-a1-approval-callback` - Operator verification of the approval decision.
* `teams-a2-operational-alert` / `teams-a4-digest` - Teams Workflows outbound
  notification bindings, which can never carry A1 approvals.
* `teams-a3-conversation` - the Operator-owned conversation channel edge.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from fdai.delivery.notifications.bindings import NotificationBindingSpec
    from fdai.shared.providers.notifications import TrustTier

SOURCE_CORE: Final[str] = "core-control-plane"
SOURCE_OPERATOR: Final[str] = "operator-service"

_A1_SEND_KEYS: Final[tuple[str, ...]] = (
    "FDAI_TEAMS_APPROVAL_ACTIVITY_URL",
    "FDAI_TEAMS_APPROVAL_TEAM_ID",
    "FDAI_TEAMS_APPROVAL_CHANNEL_ID",
)
_A1_CALLBACK_KEYS: Final[tuple[str, ...]] = (
    "FDAI_TEAMS_APPLICATION_ID",
    "FDAI_TEAMS_TENANT_ID",
    "FDAI_TEAMS_JWKS_URL",
    "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON",
    "FDAI_TEAMS_PRINCIPAL_MAP_JSON",
    "FDAI_CHATOPS_WEBHOOK_SECRET",
    "FDAI_HIL_DECISION_TOPIC",
    "FDAI_STATE_STORE_DSN",
)
_A3_KEYS: Final[tuple[str, ...]] = (
    "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS",
    "FDAI_TEAMS_APPLICATION_ID",
    "FDAI_TEAMS_TENANT_ID",
    "FDAI_TEAMS_PRINCIPAL_MAP_JSON",
    "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON",
)

_NOT_OBSERVED: Final[str] = "prerequisites are owned by another runtime and were not observed"
_INCOMPLETE: Final[str] = "configuration is incomplete"
_NOT_CONFIGURED: Final[str] = "not configured"
_UNCONFIGURED_ENDPOINT_SENTINELS: Final[frozenset[str]] = frozenset({"unconfigured", "placeholder"})


def integration_row(
    key: str,
    *,
    source: str,
    configured: bool,
    ready: bool,
    mode: str = "enabled",
    reason: str | None = None,
    observed: bool = True,
) -> dict[str, object]:
    """Build one integration row with explicit evidence attribution."""
    return {
        "key": key,
        "source": source,
        "observed": observed,
        "configured": configured,
        "ready": ready,
        "mode": mode if ready else "disabled",
        "reason": reason
        if reason is not None
        else (None if ready else _INCOMPLETE if configured else _NOT_CONFIGURED),
    }


def required_configuration(
    key: str,
    required: Sequence[str],
    env: Mapping[str, str],
    *,
    source: str,
    mode: str = "enabled",
) -> dict[str, object]:
    """Report completeness of an env-declared prerequisite set for one runtime."""
    present = tuple(bool(env.get(name, "").strip()) for name in required)
    configured = any(present)
    return integration_row(
        key,
        source=source,
        configured=configured,
        ready=all(present),
        mode=mode,
    )


def invalid_configuration(key: str, *, source: str) -> dict[str, object]:
    """Report a present but structurally invalid prerequisite set."""
    return integration_row(
        key,
        source=source,
        configured=True,
        ready=False,
        reason="configuration is invalid",
    )


def unobserved_configuration(key: str, *, source: str) -> dict[str, object]:
    """Report a prerequisite set this runtime cannot see, without guessing."""
    return integration_row(
        key,
        source=source,
        configured=False,
        ready=False,
        reason=_NOT_OBSERVED,
        observed=False,
    )


def teams_a1_send_projection(env: Mapping[str, str]) -> dict[str, object]:
    """Project Core-side Teams approval-card delivery prerequisites.

    A partially configured Bot destination is incomplete, never degraded-but-usable:
    Core refuses to send an approval card without the exact group-connected
    team, channel, and activity endpoint.
    """
    return required_configuration(
        "teams-a1-approval-send",
        _A1_SEND_KEYS,
        env,
        source=SOURCE_CORE,
    )


def teams_a1_callback_projection(env: Mapping[str, str]) -> dict[str, object]:
    """Project Operator-side approval-callback prerequisites when observable."""
    if not any(env.get(name, "").strip() for name in _A1_CALLBACK_KEYS):
        return unobserved_configuration("teams-a1-approval-callback", source=SOURCE_OPERATOR)
    row = required_configuration(
        "teams-a1-approval-callback",
        _A1_CALLBACK_KEYS,
        env,
        source=SOURCE_OPERATOR,
    )
    if row["ready"] and not _valid_json_string_map(env.get("FDAI_TEAMS_PRINCIPAL_MAP_JSON", "")):
        return invalid_configuration("teams-a1-approval-callback", source=SOURCE_OPERATOR)
    if row["ready"] and not _valid_json_string_array(
        env.get("FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON", "")
    ):
        return invalid_configuration("teams-a1-approval-callback", source=SOURCE_OPERATOR)
    return row


def teams_a3_conversation_projection(env: Mapping[str, str]) -> dict[str, object]:
    """Project Operator-owned A3 conversation edge prerequisites when observable."""
    if not any(env.get(name, "").strip() for name in _A3_KEYS):
        return unobserved_configuration("teams-a3-conversation", source=SOURCE_OPERATOR)
    enabled_channels = {
        item.strip().casefold()
        for item in env.get("FDAI_CHANNEL_EDGE_ENABLED_CHANNELS", "").split(",")
        if item.strip()
    }
    if enabled_channels and "teams" not in enabled_channels:
        return integration_row(
            "teams-a3-conversation",
            source=SOURCE_OPERATOR,
            configured=True,
            ready=False,
            reason="the channel edge does not enable Teams conversations",
        )
    return required_configuration("teams-a3-conversation", _A3_KEYS, env, source=SOURCE_OPERATOR)


def teams_notification_projections(
    env: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    """Project the A2 and A4 Teams Workflows binding rows from one binding map.

    Activation is explicit: a binding that exists but is not enabled is
    `configured` and not `ready`, and a binding whose endpoint value is still the
    deployment placeholder is never treated as enabled.
    """
    from fdai.delivery.notifications import (
        NotificationBindingKind,
        default_notification_bindings_from_env,
        parse_notification_bindings,
    )
    from fdai.shared.providers.notifications import TrustTier

    raw = env.get(
        "FDAI_NOTIFICATION_BINDINGS_JSON", ""
    ).strip() or default_notification_bindings_from_env(env)
    if not raw:
        return (
            integration_row(
                "teams-a2-operational-alert",
                source=SOURCE_CORE,
                configured=False,
                ready=False,
            ),
            integration_row(
                "teams-a4-digest",
                source=SOURCE_CORE,
                configured=False,
                ready=False,
            ),
        )
    try:
        specs = parse_notification_bindings(raw)
    except ValueError:
        return (
            invalid_configuration("teams-a2-operational-alert", source=SOURCE_CORE),
            invalid_configuration("teams-a4-digest", source=SOURCE_CORE),
        )
    teams_specs = tuple(
        spec for spec in specs if spec.kind is NotificationBindingKind.TEAMS_WORKFLOW
    )
    return (
        _teams_tier_row(
            "teams-a2-operational-alert",
            teams_specs,
            env,
            tier=TrustTier.A2_OPERATIONAL_ALERT,
        ),
        _teams_tier_row(
            "teams-a4-digest",
            teams_specs,
            env,
            tier=TrustTier.A4_DIGEST,
        ),
    )


def endpoint_is_placeholder(value: str) -> bool:
    """Report whether a resolved endpoint is still a deployment placeholder.

    Terraform seeds the Teams endpoint secret with a placeholder so the vault
    resource exists before an Owner saves a real URL. That placeholder MUST NOT
    activate delivery.
    """
    normalized = value.strip().casefold()
    if not normalized:
        return True
    return normalized in _UNCONFIGURED_ENDPOINT_SENTINELS or not normalized.startswith("https://")


def _teams_tier_row(
    key: str,
    specs: Sequence[NotificationBindingSpec],
    env: Mapping[str, str],
    *,
    tier: TrustTier,
) -> dict[str, object]:
    matching = [spec for spec in specs if tier in spec.trust_tiers]
    if not matching:
        return integration_row(key, source=SOURCE_CORE, configured=False, ready=False)
    enabled = [spec for spec in matching if spec.enabled]
    if not enabled:
        return integration_row(
            key,
            source=SOURCE_CORE,
            configured=True,
            ready=False,
            reason="a binding exists but is not activated for delivery",
        )
    unresolved = [
        spec
        for spec in enabled
        if spec.endpoint_env is None or endpoint_is_placeholder(env.get(spec.endpoint_env, ""))
    ]
    if unresolved:
        return integration_row(
            key,
            source=SOURCE_CORE,
            configured=True,
            ready=False,
            reason="an activated binding has no saved endpoint value yet",
        )
    return integration_row(key, source=SOURCE_CORE, configured=True, ready=True)


def notification_bindings_projection(env: Mapping[str, str]) -> dict[str, object]:
    """Project overall named-binding completeness with bounded counts."""
    from fdai.delivery.notifications import (
        NotificationBindingKind,
        TeamsWorkflowAuthMode,
        default_notification_bindings_from_env,
        parse_notification_bindings,
    )

    raw = env.get(
        "FDAI_NOTIFICATION_BINDINGS_JSON", ""
    ).strip() or default_notification_bindings_from_env(env)
    if not raw:
        row = integration_row(
            "notification-bindings",
            source=SOURCE_CORE,
            configured=False,
            ready=False,
        )
        row.update({"binding_count": 0, "enabled_count": 0})
        return row
    try:
        specs = parse_notification_bindings(raw)
        enabled = tuple(spec for spec in specs if spec.enabled)
        for spec in enabled:
            required_env_names = [spec.endpoint_env]
            if spec.kind is NotificationBindingKind.ACS_EMAIL:
                required_env_names.extend((spec.sender_address_env, spec.recipient_addresses_env))
            if (
                spec.kind is NotificationBindingKind.ACS_EMAIL
                or spec.auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY
            ):
                required_env_names.append(spec.identity_client_id_env)
            if any(name is None or not env.get(name, "").strip() for name in required_env_names):
                raise ValueError("enabled notification binding environment is incomplete")
            if (
                spec.kind is NotificationBindingKind.ACS_EMAIL
                and spec.recipient_addresses_env is not None
                and not _valid_json_string_array(env[spec.recipient_addresses_env])
            ):
                raise ValueError("notification binding recipients are invalid")
    except ValueError:
        row = invalid_configuration("notification-bindings", source=SOURCE_CORE)
        row.update({"binding_count": 0, "enabled_count": 0})
        return row
    row = integration_row(
        "notification-bindings",
        source=SOURCE_CORE,
        configured=True,
        ready=True,
    )
    row.update({"binding_count": len(specs), "enabled_count": len(enabled)})
    return row


def integration_projection(env: Mapping[str, str]) -> list[dict[str, object]]:
    """Build the complete source-attributed integration list for one runtime.

    This is the single implementation behind both the deployed Core projection
    and the local materialized projection, so the two venues can never drift
    into different readiness vocabularies.
    """
    a2_row, a4_row = teams_notification_projections(env)
    email = required_configuration(
        "email",
        (
            "FDAI_EMAIL_ENDPOINT",
            "FDAI_EMAIL_SENDER_ADDRESS",
            "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON",
            "FDAI_NOTIFICATION_MI_CLIENT_ID",
        ),
        env,
        source=SOURCE_CORE,
    )
    if email["ready"] and not _valid_json_string_array(
        env.get("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON", "")
    ):
        email = invalid_configuration("email", source=SOURCE_CORE)
    gitops = required_configuration(
        "gitops",
        ("FDAI_GITOPS_TOKEN", "FDAI_GITOPS_OWNER", "FDAI_GITOPS_REPO"),
        env,
        source=SOURCE_CORE,
    )
    jira = required_configuration(
        "jira",
        (
            "FDAI_JIRA_BASE_URL",
            "FDAI_JIRA_ACCOUNT_EMAIL",
            "FDAI_JIRA_API_TOKEN_SECRET",
            "FDAI_JIRA_TOOL_MAP_JSON",
            "FDAI_STATE_STORE_DSN",
        ),
        env,
        source=SOURCE_CORE,
        mode="enforce" if env.get("FDAI_JIRA_ENFORCE", "").strip() == "1" else "shadow",
    )
    if jira["ready"] and not _valid_json_string_map(env.get("FDAI_JIRA_TOOL_MAP_JSON", "")):
        jira = invalid_configuration("jira", source=SOURCE_CORE)
    human_access = required_configuration(
        "human-access",
        (
            "FDAI_HUMAN_ACCESS_MI_CLIENT_ID",
            "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON",
            "FDAI_STATE_STORE_DSN",
        ),
        env,
        source=SOURCE_CORE,
        mode="shadow",
    )
    if human_access["ready"] and not _valid_human_access_role_groups(
        env.get("FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "")
    ):
        human_access = invalid_configuration("human-access", source=SOURCE_CORE)
    human_access.update({"available": human_access["ready"], "authority_mode": "shadow"})
    return [
        teams_a1_send_projection(env),
        teams_a1_callback_projection(env),
        a2_row,
        a4_row,
        teams_a3_conversation_projection(env),
        notification_bindings_projection(env),
        email,
        gitops,
        jira,
        human_access,
    ]


def _valid_human_access_role_groups(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    expected = {"Reader", "Contributor", "Approver", "Owner"}
    if not isinstance(value, dict) or set(value) != expected:
        return False
    group_ids = tuple(value.values())
    return all(isinstance(item, str) and bool(item.strip()) for item in group_ids) and len(
        set(group_ids)
    ) == len(group_ids)


def _valid_json_string_array(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _valid_json_string_map(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(key, str) and key.strip() and isinstance(item, str) and item.strip()
            for key, item in value.items()
        )
    )


__all__ = [
    "SOURCE_CORE",
    "SOURCE_OPERATOR",
    "endpoint_is_placeholder",
    "integration_projection",
    "integration_row",
    "invalid_configuration",
    "notification_bindings_projection",
    "required_configuration",
    "teams_a1_callback_projection",
    "teams_a1_send_projection",
    "teams_a3_conversation_projection",
    "teams_notification_projections",
    "unobserved_configuration",
]
