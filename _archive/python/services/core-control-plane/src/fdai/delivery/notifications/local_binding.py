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

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from fdai_service_contracts.notification_binding import (
    LOCAL_TEAMS_BINDING_STATE_KEY,
    LocalTeamsBindingRecordError,
    decode_local_binding_record,
    local_binding_key_material,
)

from .slack import SLACK_CHAT_POST_MESSAGE_URL

ACTIVATION_ENV: Final[str] = "FDAI_TEAMS_NOTIFICATION_ACTIVATION"
DEFAULT_LOCAL_ENDPOINT_ENV: Final[str] = "FDAI_TEAMS_OPS_ENDPOINT"
DEFAULT_LOCAL_SLACK_ENDPOINT_ENV: Final[str] = "FDAI_SLACK_OPS_WEBHOOK_URL"
DEFAULT_LOCAL_SLACK_CHANNEL_ENV: Final[str] = "FDAI_SLACK_OPS_CHANNEL_ID"
DEFAULT_LOCAL_SLACK_BOT_TOKEN_ENV: Final[str] = "FDAI_SLACK_BOT_TOKEN"  # noqa: S105 - env variable name
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_MAX_LOCAL_BACKUP_BYTES: Final[int] = 16_384
_SLACK_CHANNEL_ID_RE: Final = re.compile(r"^[CDG][A-Z0-9]{8,14}$")
_LOGGER = logging.getLogger("fdai.startup")


def _default_local_fdai_dir() -> Path | None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return None
    fdai_dir = Path(__file__).resolve().parents[5] / ".fdai"
    if (fdai_dir / "local-runtime.env").is_file():
        return fdai_dir
    return None


def _read_private_backup(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        _LOGGER.warning("local_teams_binding_unusable", extra={"reason": "backup_symlink"})
        return None
    try:
        stat_result = path.stat()
    except OSError:
        return None
    if stat_result.st_mode & 0o077 or stat_result.st_size > _MAX_LOCAL_BACKUP_BYTES:
        _LOGGER.warning("local_teams_binding_unusable", extra={"reason": "backup_permissions"})
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOGGER.warning("local_teams_binding_unusable", extra={"reason": "backup_malformed"})
        return None
    return payload if isinstance(payload, dict) else None


def _read_local_slack_overrides(fdai_dir: Path | None) -> dict[str, str]:
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
            or input_stat.st_size > _MAX_LOCAL_BACKUP_BYTES
            or channel_stat.st_size > 256
        ):
            return {}
        channel_id = channel_file.read_text(encoding="utf-8").strip()
        if _SLACK_CHANNEL_ID_RE.fullmatch(channel_id) is None:
            return {}
        bot_token = ""
        for raw_line in input_env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if line.startswith("FDAI_SLACK_BOT_TOKEN="):
                bot_token = line.split("=", 1)[1].strip().strip("'\"")
                break
        if not bot_token or any(ch.isspace() for ch in bot_token):
            return {}
    except OSError:
        return {}
    return {
        DEFAULT_LOCAL_SLACK_ENDPOINT_ENV: SLACK_CHAT_POST_MESSAGE_URL,
        DEFAULT_LOCAL_SLACK_CHANNEL_ENV: channel_id,
        DEFAULT_LOCAL_SLACK_BOT_TOKEN_ENV: bot_token,
    }


class LocalBindingStateReader(Protocol):
    """Read one durable local state record by key."""

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


def _candidate_key_materials(key_material: str) -> tuple[str, ...]:
    normalized = local_binding_key_material(key_material)
    if normalized.startswith("postgresql://"):
        alt = "postgresql+psycopg://" + normalized[len("postgresql://") :]
        return (normalized, alt)
    if normalized.startswith("postgresql+psycopg://"):
        alt = "postgresql://" + normalized[len("postgresql+psycopg://") :]
        return (normalized, alt)
    return (normalized,)


@dataclass(frozen=True, slots=True)
class LocalEncryptedNotificationBindingStore:
    """Resolve the activated local Teams endpoint without exposing it elsewhere."""

    state_store: LocalBindingStateReader
    key_material: str = field(repr=False)
    backup_path: Path | None = None

    async def load_endpoint(self) -> str | None:
        """Return the saved endpoint, or ``None`` when no usable record exists."""
        record = await self.state_store.read_state(LOCAL_TEAMS_BINDING_STATE_KEY)
        if record is None:
            resolved_backup = self.backup_path
            if resolved_backup is None:
                fdai_dir = _default_local_fdai_dir()
                if fdai_dir is not None:
                    resolved_backup = fdai_dir / "local-teams-workflow-binding.json"
            if resolved_backup is not None:
                record = _read_private_backup(resolved_backup)
        if record is None:
            return None
        for candidate in _candidate_key_materials(self.key_material):
            try:
                decoded = decode_local_binding_record(record, key_material=candidate)
            except LocalTeamsBindingRecordError:
                continue
            if decoded is not None:
                endpoint, _version = decoded
                return endpoint
        _LOGGER.warning("local_teams_binding_unusable", extra={"reason": "record_invalid"})
        return None


def notification_activation_requested(environment: Mapping[str, str]) -> bool:
    """Report whether a deployment explicitly activated Teams notification delivery."""
    return environment.get(ACTIVATION_ENV, "").strip().casefold() in _TRUTHY


async def resolve_local_notification_endpoints(
    *,
    environment: Mapping[str, str],
    state_store: LocalBindingStateReader | None,
    key_material: str | None,
    backup_path: Path | None = None,
    local_fdai_dir: Path | None = None,
) -> dict[str, str]:
    """Build endpoint overrides for activated local Teams and Slack bindings.

    Returns an empty mapping when activation was not requested, when the local
    record is missing or unusable, or when the environment already supplies the
    endpoint. Saving a binding never reaches this function, so a save can never
    enable a destination on its own.
    """
    if not notification_activation_requested(environment):
        return {}
    if state_store is None or not key_material:
        return {}
    overrides: dict[str, str] = {}
    if not environment.get(DEFAULT_LOCAL_ENDPOINT_ENV, "").strip():
        endpoint = await LocalEncryptedNotificationBindingStore(
            state_store=state_store,
            key_material=local_binding_key_material(key_material),
            backup_path=backup_path,
        ).load_endpoint()
        if endpoint is None:
            _LOGGER.info(
                "teams_notification_activation_pending",
                extra={"reason": "no_saved_local_binding"},
            )
        else:
            overrides[DEFAULT_LOCAL_ENDPOINT_ENV] = endpoint
    if (
        not environment.get("FDAI_SLACK_OPS_WEBHOOK_URL", "").strip()
        and not environment.get(DEFAULT_LOCAL_SLACK_BOT_TOKEN_ENV, "").strip()
    ):
        fdai_dir = local_fdai_dir if local_fdai_dir is not None else _default_local_fdai_dir()
        overrides.update(_read_local_slack_overrides(fdai_dir))
    return overrides


def resolve_local_backup_notification_endpoints(
    *,
    environment: Mapping[str, str],
    key_material: str | None = None,
    backup_path: Path | None = None,
    local_fdai_dir: Path | None = None,
) -> dict[str, str]:
    """Synchronously resolve activated local Teams backup and Slack overrides."""
    if not notification_activation_requested(environment):
        return {}
    resolved_key = (
        key_material
        or environment.get("FDAI_STATE_STORE_DSN", "").strip()
        or environment.get("FDAI_DATABASE_URL", "").strip()
    )
    if not resolved_key:
        return {}
    overrides: dict[str, str] = {}
    fdai_dir = local_fdai_dir if local_fdai_dir is not None else _default_local_fdai_dir()
    if not environment.get(DEFAULT_LOCAL_ENDPOINT_ENV, "").strip():
        resolved_backup = backup_path
        if resolved_backup is None and fdai_dir is not None:
            resolved_backup = fdai_dir / "local-teams-workflow-binding.json"
        record = _read_private_backup(resolved_backup) if resolved_backup is not None else None
        if record is not None:
            for candidate in _candidate_key_materials(resolved_key):
                try:
                    decoded = decode_local_binding_record(record, key_material=candidate)
                except LocalTeamsBindingRecordError:
                    continue
                if decoded is not None:
                    endpoint, _version = decoded
                    overrides[DEFAULT_LOCAL_ENDPOINT_ENV] = endpoint
                    break
    if (
        not environment.get(DEFAULT_LOCAL_SLACK_ENDPOINT_ENV, "").strip()
        and not environment.get(DEFAULT_LOCAL_SLACK_BOT_TOKEN_ENV, "").strip()
    ):
        overrides.update(_read_local_slack_overrides(fdai_dir))
    return overrides


__all__ = [
    "ACTIVATION_ENV",
    "DEFAULT_LOCAL_ENDPOINT_ENV",
    "DEFAULT_LOCAL_SLACK_BOT_TOKEN_ENV",
    "DEFAULT_LOCAL_SLACK_CHANNEL_ENV",
    "DEFAULT_LOCAL_SLACK_ENDPOINT_ENV",
    "LocalBindingStateReader",
    "LocalEncryptedNotificationBindingStore",
    "notification_activation_requested",
    "resolve_local_backup_notification_endpoints",
    "resolve_local_notification_endpoints",
]
