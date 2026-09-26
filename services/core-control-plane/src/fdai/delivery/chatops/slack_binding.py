"""Fail-closed selection of the outbound Slack HIL delivery adapter."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from fdai.delivery.chatops.slack_adapter import SlackHilAdapter, SlackHilAdapterConfig

_SLACK_KEYS = (
    "FDAI_SLACK_APPROVAL_API_URL",
    "FDAI_SLACK_APPROVAL_CHANNEL_ID",
    "FDAI_SLACK_APPROVAL_BOT_TOKEN",
)


def build_slack_hil_channel(
    environment: Mapping[str, str],
    *,
    http_client: httpx.AsyncClient | None,
    teams_configured: bool,
) -> SlackHilAdapter | None:
    """Select Slack only for a complete, exclusive and HTTP-backed configuration."""

    values = tuple(environment.get(key, "").strip() for key in _SLACK_KEYS)
    if not any(values):
        return None
    if not all(values):
        raise RuntimeError("Slack approval API URL, channel ID, and bot token MUST be set together")
    if teams_configured:
        raise RuntimeError("Slack and Teams HIL transports cannot be selected together")
    if http_client is None:
        raise RuntimeError("Slack approval delivery requires a composition-owned HTTP client")
    try:
        config = SlackHilAdapterConfig(
            api_url=values[0],
            channel_id=values[1],
            bot_token=values[2],
        )
    except ValueError as exc:
        raise RuntimeError("Slack approval configuration is invalid") from exc
    return SlackHilAdapter(config=config, http_client=http_client)
