"""Fail-closed selection of the outbound Slack HIL delivery adapter."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import httpx

from fdai.delivery.chatops.slack_adapter import (
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)

LOCAL_SLACK_APPROVAL_ACTIVATION_ENV: Final[str] = "FDAI_LOCAL_SLACK_APPROVAL_ACTIVATION"
_SLACK_KEYS = (
    "FDAI_SLACK_APPROVAL_API_URL",
    "FDAI_SLACK_APPROVAL_CHANNEL_ID",
    "FDAI_SLACK_APPROVAL_BOT_TOKEN",
)
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_MAX_LOCAL_INPUT_BYTES: Final[int] = 16_384
_SLACK_CHANNEL_ID_RE: Final = re.compile(r"^[CDG][A-Z0-9]{8,14}$")


def _default_local_fdai_dir() -> Path | None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None
    fdai_dir = Path(__file__).resolve().parents[5] / ".fdai"
    if (fdai_dir / "local-runtime.env").is_file():
        return fdai_dir
    return None


def _read_local_slack_approval_overrides(fdai_dir: Path | None) -> dict[str, str]:
    if fdai_dir is None:
        return {}
    input_env = fdai_dir / "local-channel-edge-input.env"
    channel_file = fdai_dir / "slack-public-channel"
    if not input_env.exists() or not channel_file.exists():
        return {}
    if input_env.is_symlink() or channel_file.is_symlink():
        return {}
    try:
        input_stat = input_env.stat()
        channel_stat = channel_file.stat()
        if (
            input_stat.st_mode & 0o077
            or channel_stat.st_mode & 0o077
            or input_stat.st_size > _MAX_LOCAL_INPUT_BYTES
            or channel_stat.st_size > 256
        ):
            return {}
        channel_id = channel_file.read_text(encoding="utf-8").strip()
        if _SLACK_CHANNEL_ID_RE.fullmatch(channel_id) is None:
            return {}
        bot_token = ""
        for raw_line in input_env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == "FDAI_SLACK_BOT_TOKEN":
                bot_token = val.strip().strip("'\"")
                break
        if not bot_token:
            return {}
    except OSError:
        return {}
    return {
        "FDAI_SLACK_APPROVAL_API_URL": SLACK_POST_URL,
        "FDAI_SLACK_APPROVAL_CHANNEL_ID": channel_id,
        "FDAI_SLACK_APPROVAL_BOT_TOKEN": bot_token,
    }


def resolve_local_slack_approval_environment(
    environment: Mapping[str, str],
    *,
    fdai_dir: Path | None = None,
) -> dict[str, str]:
    """Overlay owner-only local Slack A1 settings when explicitly activated."""
    merged = dict(environment)
    if any(merged.get(key, "").strip() for key in _SLACK_KEYS):
        return merged
    if merged.get(LOCAL_SLACK_APPROVAL_ACTIVATION_ENV, "").strip().casefold() not in _TRUTHY:
        return merged
    resolved_dir = _default_local_fdai_dir() if fdai_dir is None else fdai_dir
    for key, value in _read_local_slack_approval_overrides(resolved_dir).items():
        merged.setdefault(key, value)
    return merged


def build_slack_hil_channel(
    environment: Mapping[str, str],
    *,
    http_client: httpx.AsyncClient | None,
    teams_configured: bool,
    fdai_dir: Path | None = None,
) -> SlackHilAdapter | None:
    """Select Slack only for a complete, exclusive and HTTP-backed configuration."""

    resolved = resolve_local_slack_approval_environment(environment, fdai_dir=fdai_dir)
    values = tuple(resolved.get(key, "").strip() for key in _SLACK_KEYS)
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
