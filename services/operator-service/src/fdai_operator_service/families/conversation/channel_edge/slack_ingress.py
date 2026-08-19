"""Authenticate and normalize bounded Slack Events API requests."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai_operator_service.families.conversation.channel_edge.models import (
    MAX_ATTACHMENT_COUNT,
    ChannelAttachment,
    ChannelKind,
    InboundChannelTurn,
)

_DEFAULT_MAX_BODY_BYTES = 256_000
_DEFAULT_REPLAY_WINDOW = timedelta(minutes=5)
_MAX_CHALLENGE_CHARS = 512


@dataclass(frozen=True, slots=True)
class SlackIngressConfig:
    """Configure exact signature, workspace, and canonical principal admission."""

    signing_secret: str = field(repr=False)
    team_id: str
    principal_by_sender_id: Mapping[str, str]
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    replay_window: timedelta = _DEFAULT_REPLAY_WINDOW

    def __post_init__(self) -> None:
        if not self.signing_secret:
            raise ValueError("Slack signing_secret MUST be non-empty")
        if not self.team_id or len(self.team_id) > 200:
            raise ValueError("Slack team_id MUST be bounded and non-empty")
        if not self.principal_by_sender_id or any(
            not sender
            or len(sender) > 200
            or not principal
            or len(principal) > 256
            or sender == principal
            for sender, principal in self.principal_by_sender_id.items()
        ):
            raise ValueError("Slack principal mapping MUST contain distinct bounded identities")
        if self.max_body_bytes < 1:
            raise ValueError("Slack max_body_bytes MUST be positive")
        if self.replay_window <= timedelta(0):
            raise ValueError("Slack replay_window MUST be positive")


class SlackIngressAction(StrEnum):
    """Authenticated Slack route decision."""

    ACCEPTED = "accepted"
    CHALLENGE = "challenge"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class SlackIngressResult:
    """Return one authenticated turn, challenge, or content-free ignore decision."""

    action: SlackIngressAction
    turn: InboundChannelTurn | None = None
    principal_id: str | None = None
    verification_ref: str | None = None
    challenge: str | None = None

    def __post_init__(self) -> None:
        accepted_fields = self.turn is not None and self.principal_id is not None
        if self.action is SlackIngressAction.ACCEPTED and not accepted_fields:
            raise ValueError("accepted Slack ingress requires a turn and principal")
        if self.action is SlackIngressAction.CHALLENGE and self.challenge is None:
            raise ValueError("Slack challenge ingress requires a challenge")
        if self.action is SlackIngressAction.IGNORED and any(
            value is not None
            for value in (self.turn, self.principal_id, self.verification_ref, self.challenge)
        ):
            raise ValueError("ignored Slack ingress cannot carry content")


class SlackIngressError(ValueError):
    """A Slack request failed before queue admission without retaining content."""

    def __init__(self, message: str, *, code: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class SlackIngressVerifier:
    """Verify the exact signed body and replace vendor identity with one principal."""

    def __init__(self, config: SlackIngressConfig) -> None:
        self._config = config

    def parse(
        self,
        *,
        body: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
    ) -> SlackIngressResult:
        """Authenticate one raw request before parsing any operator identity."""
        if received_at.tzinfo is None:
            raise ValueError("Slack received_at MUST include a timezone")
        if len(body) > self._config.max_body_bytes:
            raise SlackIngressError(
                "Slack request body exceeds the configured limit",
                code="body_too_large",
                http_status=413,
            )
        timestamp_text = _header(headers, "x-slack-request-timestamp")
        signature = _header(headers, "x-slack-signature")
        try:
            timestamp = int(timestamp_text)
            observed_at = datetime.fromtimestamp(timestamp, tz=received_at.tzinfo)
        except (OSError, OverflowError, TypeError, ValueError) as exc:
            raise SlackIngressError(
                "Slack request timestamp is invalid",
                code="invalid_timestamp",
                http_status=401,
            ) from exc
        if abs(received_at - observed_at) > self._config.replay_window:
            raise SlackIngressError(
                "Slack request is outside the replay window",
                code="stale_request",
                http_status=401,
            )
        expected = (
            "v0="
            + hmac.new(
                self._config.signing_secret.encode(),
                b"v0:" + timestamp_text.encode("ascii") + b":" + body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            raise SlackIngressError(
                "Slack request signature is invalid",
                code="invalid_signature",
                http_status=401,
            )
        payload = _json_object(body)
        request_type = payload.get("type")
        if request_type == "url_verification":
            return SlackIngressResult(
                action=SlackIngressAction.CHALLENGE,
                challenge=_text(payload, "challenge", maximum=_MAX_CHALLENGE_CHARS),
            )
        if request_type != "event_callback":
            return SlackIngressResult(action=SlackIngressAction.IGNORED)
        if _text(payload, "team_id", maximum=200) != self._config.team_id:
            raise SlackIngressError(
                "Slack workspace is not authorized",
                code="unknown_workspace",
                http_status=403,
            )
        event = payload.get("event")
        if not isinstance(event, Mapping):
            raise SlackIngressError(
                "Slack event payload is invalid", code="invalid_payload", http_status=400
            )
        if event.get("type") != "message":
            return SlackIngressResult(action=SlackIngressAction.IGNORED)
        subtype = event.get("subtype")
        if subtype not in {None, "file_share"} or any(
            event.get(field_name) is not None for field_name in ("bot_id", "bot_profile", "app_id")
        ):
            return SlackIngressResult(action=SlackIngressAction.IGNORED)
        sender_id = _text(event, "user", maximum=200)
        principal_id = self._config.principal_by_sender_id.get(sender_id)
        if principal_id is None:
            raise SlackIngressError(
                "Slack sender is not authorized", code="unknown_sender", http_status=403
            )
        event_ts = _text(event, "ts", maximum=200)
        thread_value = event.get("thread_ts")
        thread_id = (
            _bounded_text(thread_value, name="thread_ts", maximum=200)
            if thread_value is not None
            else event_ts
        )
        text_value = event.get("text", "")
        if not isinstance(text_value, str):
            raise SlackIngressError(
                "Slack message text is invalid", code="invalid_payload", http_status=400
            )
        try:
            turn = InboundChannelTurn(
                channel_kind=ChannelKind.SLACK,
                channel_id=_text(event, "channel", maximum=200),
                message_id=_text(payload, "event_id", maximum=200),
                sender_id=sender_id,
                text=text_value,
                thread_id=thread_id,
                attachments=_attachments(event.get("files", ())),
            )
        except ValueError as exc:
            raise SlackIngressError(
                "Slack message violates the channel contract",
                code="invalid_payload",
                http_status=400,
            ) from exc
        verification_digest = hashlib.sha256(
            f"{self._config.team_id}:{sender_id}".encode()
        ).hexdigest()
        return SlackIngressResult(
            action=SlackIngressAction.ACCEPTED,
            turn=turn,
            principal_id=principal_id,
            verification_ref=f"slack-mapping:{verification_digest}",
        )


def _header(headers: Mapping[str, str], name: str) -> str:
    value = next((value for key, value in headers.items() if key.lower() == name), "")
    if not value:
        raise SlackIngressError(
            "Slack authentication headers are missing",
            code="missing_authentication",
            http_status=401,
        )
    return value


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SlackIngressError(
            "Slack request body is invalid JSON", code="invalid_json", http_status=400
        ) from exc
    if not isinstance(payload, Mapping):
        raise SlackIngressError(
            "Slack request body MUST be an object", code="invalid_payload", http_status=400
        )
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _text(value: Mapping[str, Any], key: str, *, maximum: int) -> str:
    return _bounded_text(value.get(key), name=key, maximum=maximum)


def _bounded_text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise SlackIngressError(f"Slack {name} is invalid", code="invalid_payload", http_status=400)
    return value


def _attachments(raw: object) -> tuple[ChannelAttachment, ...]:
    if raw in (None, ()):
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENT_COUNT:
        raise SlackIngressError(
            "Slack file metadata exceeds the channel limit",
            code="invalid_payload",
            http_status=400,
        )
    attachments: list[ChannelAttachment] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise SlackIngressError(
                "Slack file metadata is invalid", code="invalid_payload", http_status=400
            )
        size = item.get("size")
        if not isinstance(size, int) or isinstance(size, bool):
            raise SlackIngressError(
                "Slack file size is invalid", code="invalid_payload", http_status=400
            )
        try:
            attachments.append(
                ChannelAttachment(
                    source_ref="slack-file:"
                    + _bounded_text(item.get("id"), name="file id", maximum=200),
                    name=_bounded_text(item.get("name"), name="file name", maximum=512),
                    size_bytes=size,
                    media_type_hint=(
                        _bounded_text(item.get("mimetype"), name="file media type", maximum=256)
                        if item.get("mimetype") is not None
                        else "application/octet-stream"
                    ),
                )
            )
        except ValueError as exc:
            raise SlackIngressError(
                "Slack file metadata violates the channel contract",
                code="invalid_payload",
                http_status=400,
            ) from exc
    return tuple(attachments)


__all__ = [
    "SlackIngressAction",
    "SlackIngressConfig",
    "SlackIngressError",
    "SlackIngressResult",
    "SlackIngressVerifier",
]
