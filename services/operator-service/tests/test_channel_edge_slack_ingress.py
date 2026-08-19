"""Focused security checks for Operator-owned Slack ingress."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
    SlackIngressConfig,
    SlackIngressError,
    SlackIngressVerifier,
)

_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
_SECRET = "slack-signing-secret-example"


def _verifier() -> SlackIngressVerifier:
    return SlackIngressVerifier(
        SlackIngressConfig(
            signing_secret=_SECRET,
            team_id="team-example",
            principal_by_sender_id={"user-example": "principal-example"},
        )
    )


def _body(**event_overrides: object) -> bytes:
    event: dict[str, object] = {
        "type": "message",
        "user": "user-example",
        "channel": "channel-example",
        "ts": "1.000",
        "text": "Show current evidence.",
    }
    event.update(event_overrides)
    return json.dumps(
        {"type": "event_callback", "team_id": "team-example", "event_id": "event-1", "event": event}
    ).encode()


def _headers(body: bytes, *, at: datetime = _NOW) -> dict[str, str]:
    timestamp = str(int(at.timestamp()))
    signature = (
        "v0="
        + hmac.new(
            _SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256
        ).hexdigest()
    )
    return {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}


def test_slack_ingress_maps_principal_and_strips_payload_urls() -> None:
    body = _body(
        subtype="file_share",
        files=[
            {
                "id": "file-example",
                "name": "evidence.txt",
                "size": 12,
                "mimetype": "text/plain",
                "url_private": "https://example.invalid/must-not-survive",
            }
        ],
    )

    result = _verifier().parse(body=body, headers=_headers(body), received_at=_NOW)

    assert result.action is SlackIngressAction.ACCEPTED
    assert result.principal_id == "principal-example"
    assert result.turn is not None and result.turn.channel_kind is ChannelKind.SLACK
    assert result.turn.attachments[0].source_ref == "slack-file:file-example"
    assert "url" not in repr(result.turn.attachments[0]).lower()
    assert result.verification_ref is not None
    assert "user-example" not in result.verification_ref


@pytest.mark.parametrize(
    ("mutate", "code", "status"),
    [
        (lambda body, headers: (body + b" ", headers), "invalid_signature", 401),
        (
            lambda body, _headers: (body, {"X-Slack-Request-Timestamp": "1"}),
            "missing_authentication",
            401,
        ),
        (
            lambda body, headers: (body, headers),
            "stale_request",
            401,
        ),
    ],
)
def test_slack_ingress_rejects_signature_and_replay_failures(
    mutate: object, code: str, status: int
) -> None:
    body = _body()
    headers = _headers(body)
    mutate_call = mutate
    assert callable(mutate_call)
    changed_body, changed_headers = mutate_call(body, headers)
    received_at = _NOW + timedelta(minutes=6) if code == "stale_request" else _NOW

    with pytest.raises(SlackIngressError) as error:
        _verifier().parse(body=changed_body, headers=changed_headers, received_at=received_at)

    assert error.value.code == code and error.value.http_status == status


def test_slack_ingress_rejects_unknown_workspace_sender_and_duplicate_json_keys() -> None:
    unknown_sender = _body(user="other-user")
    with pytest.raises(SlackIngressError, match="sender") as sender_error:
        _verifier().parse(body=unknown_sender, headers=_headers(unknown_sender), received_at=_NOW)
    assert sender_error.value.http_status == 403

    unknown_workspace = _body().replace(b"team-example", b"team-unknown")
    with pytest.raises(SlackIngressError, match="workspace") as workspace_error:
        _verifier().parse(
            body=unknown_workspace,
            headers=_headers(unknown_workspace),
            received_at=_NOW,
        )
    assert workspace_error.value.http_status == 403

    duplicate = b'{"type":"event_callback","type":"url_verification"}'
    with pytest.raises(SlackIngressError) as duplicate_error:
        _verifier().parse(body=duplicate, headers=_headers(duplicate), received_at=_NOW)
    assert duplicate_error.value.code == "invalid_json"


def test_slack_ingress_ignores_bot_loops_and_accepts_signed_challenge() -> None:
    bot = _body(bot_id="bot-example")
    ignored = _verifier().parse(body=bot, headers=_headers(bot), received_at=_NOW)
    assert ignored.action is SlackIngressAction.IGNORED

    challenge = json.dumps({"type": "url_verification", "challenge": "challenge"}).encode()
    accepted = _verifier().parse(
        body=challenge,
        headers=_headers(challenge),
        received_at=_NOW,
    )
    assert accepted.action is SlackIngressAction.CHALLENGE
    assert accepted.challenge == "challenge"
