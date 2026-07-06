"""TeamsHilAdapter — HTTP-level round-trip via httpx.MockTransport.

Verifies the wire contract the P2 risk-gate + HIL notifier rely on:

- Adaptive Card body is sent to the configured webhook URL with the
  correct content-type and (optionally) HMAC signature.
- Body is JSON-encoded and includes ``approve`` / ``reject``
  ``Action.Submit`` buttons that carry the opaque ``approval_id``.
- HMAC signature header is present + verifiable when a secret is
  configured; absent when no secret is set.
- Bot Framework mode attaches a ``Bearer`` token from the injected
  :class:`WorkloadIdentity` and rejects a config that supplies both
  a secret and an identity.
- ``poll`` returns :data:`HilDecision.PENDING` in P1 (no back-channel).
- :meth:`TeamsHilAdapter.parse_response` maps ``approve`` / ``reject``
  / ``timeout`` / unknown payloads to the right :class:`HilDecision`
  values, and rejects a payload without ``approval_id``.
- Non-2xx / non-JSON / transport failures raise :class:`HilChannelError`
  with a truncated snippet — no raw response body leaks.

No real Teams endpoints are contacted; every test builds an
``httpx.AsyncClient`` on top of :class:`httpx.MockTransport`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from aiopspilot.delivery.chatops.teams_adapter import (
    TeamsHilAdapter,
    TeamsHilAdapterConfig,
)
from aiopspilot.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannelError,
    HilDecision,
)
from aiopspilot.shared.providers.testing.workload_identity import (
    StaticWorkloadIdentity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WEBHOOK_URL = "https://mock-teams.local/webhookb2/example@tenant/IncomingWebhook/abc/def"
_WEBHOOK_SECRET = "s3cret-shared-hmac-key"  # noqa: S105 — deterministic test literal
_BEARER = "test-bot-token"  # noqa: S105


def _request(
    *,
    approval_id: str = "appr-1",
    correlation_id: str = "corr-1",
    action_id: str = "00000000-0000-0000-0000-000000000042",
    action_type: str = "remediate.tag-missing-owner",
    rule_ids: tuple[str, ...] = ("example.tag.owner-required",),
    target_resource_ref: str = "resource:example/rg/vm-1",
    blast_radius_summary: str = "1 resource in rg-example",
    reasons: tuple[str, ...] = ("action_type_in_shadow_mode",),
    ttl_seconds: int = 1800,
    action_hash: str = "hash-abc",
) -> HilApprovalRequest:
    return HilApprovalRequest(
        approval_id=approval_id,
        correlation_id=correlation_id,
        action_id=action_id,
        action_type=action_type,
        rule_ids=rule_ids,
        target_resource_ref=target_resource_ref,
        blast_radius_summary=blast_radius_summary,
        reasons=reasons,
        ttl_seconds=ttl_seconds,
        action_hash=action_hash,
    )


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _adapter(
    client: httpx.AsyncClient,
    *,
    webhook_secret: str | None = None,
    identity: StaticWorkloadIdentity | None = None,
    approve_callback_url: str | None = None,
    reject_callback_url: str | None = None,
) -> TeamsHilAdapter:
    return TeamsHilAdapter(
        config=TeamsHilAdapterConfig(
            webhook_url=_WEBHOOK_URL,
            webhook_secret=webhook_secret,
            approve_callback_url=approve_callback_url,
            reject_callback_url=reject_callback_url,
        ),
        http_client=client,
        identity=identity,
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_empty_webhook_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="webhook_url MUST NOT be empty"):
        TeamsHilAdapter(
            config=TeamsHilAdapterConfig(webhook_url=""),
            http_client=httpx.AsyncClient(),
        )


def test_whitespace_webhook_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="webhook_url MUST NOT be empty"):
        TeamsHilAdapter(
            config=TeamsHilAdapterConfig(webhook_url="   "),
            http_client=httpx.AsyncClient(),
        )


def test_zero_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
        TeamsHilAdapter(
            config=TeamsHilAdapterConfig(webhook_url=_WEBHOOK_URL, timeout_seconds=0),
            http_client=httpx.AsyncClient(),
        )


def test_tiny_error_body_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_error_body_bytes MUST be >= 64"):
        TeamsHilAdapter(
            config=TeamsHilAdapterConfig(webhook_url=_WEBHOOK_URL, max_error_body_bytes=32),
            http_client=httpx.AsyncClient(),
        )


def test_secret_and_identity_are_mutually_exclusive() -> None:
    identity = StaticWorkloadIdentity(
        audience="https://api.botframework.com/.default", token=_BEARER
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        TeamsHilAdapter(
            config=TeamsHilAdapterConfig(
                webhook_url=_WEBHOOK_URL,
                webhook_secret=_WEBHOOK_SECRET,
            ),
            http_client=httpx.AsyncClient(),
            identity=identity,
        )


# ---------------------------------------------------------------------------
# Happy path — send + receipt
# ---------------------------------------------------------------------------


async def test_send_posts_adaptive_card_and_returns_receipt() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert isinstance(receipt, HilApprovalReceipt)
    assert receipt.approval_id == "appr-1"
    assert receipt.channel_ref.startswith("teams:")
    assert receipt.sent_at.tzinfo is not None

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == _WEBHOOK_URL
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["Accept"] == "application/json"

    body = json.loads(req.content)
    assert body["type"] == "message"
    assert body["attachments"][0]["contentType"] == ("application/vnd.microsoft.card.adaptive")
    card = body["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.5"

    # Two Action.Submit buttons carrying the approval_id.
    actions = card["actions"]
    titles = [a["title"] for a in actions]
    assert titles == ["Approve", "Reject"]
    approve_data = actions[0]["data"]
    reject_data = actions[1]["data"]
    assert approve_data["action"] == "approve"
    assert approve_data["approval_id"] == "appr-1"
    assert approve_data["action_hash"] == "hash-abc"
    assert reject_data["action"] == "reject"

    # Facts include target + blast radius + rules.
    facts = card["body"][2]["facts"]
    fact_map = {f["title"]: f["value"] for f in facts}
    assert fact_map["Action"] == "remediate.tag-missing-owner"
    assert fact_map["Target"] == "resource:example/rg/vm-1"
    assert fact_map["Blast radius"] == "1 resource in rg-example"
    assert fact_map["Rules"] == "example.tag.owner-required"


async def test_send_uses_response_body_id_as_channel_ref() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "msg-42"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert receipt.channel_ref == "teams:msg-42"


async def test_send_uses_message_id_when_id_missing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messageId": "mid-99"})

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert receipt.channel_ref == "teams:mid-99"


async def test_send_falls_back_to_uuid_when_body_opaque() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"1")  # non-JSON, non-empty

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert receipt.channel_ref.startswith("teams:appr-1:")


async def test_send_falls_back_to_uuid_when_body_is_invalid_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not valid json")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert receipt.channel_ref.startswith("teams:appr-1:")


async def test_send_falls_back_to_uuid_on_empty_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)  # empty body

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = await adapter.send(_request())

    assert receipt.channel_ref.startswith("teams:appr-1:")


# ---------------------------------------------------------------------------
# Auth header shape
# ---------------------------------------------------------------------------


async def test_send_without_secret_has_no_signature_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        await adapter.send(_request())

    assert "X-AIOpsPilot-Signature" not in seen[0].headers
    assert "X-AIOpsPilot-Timestamp" not in seen[0].headers
    assert "Authorization" not in seen[0].headers


async def test_send_with_secret_attaches_hmac_signature() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client, webhook_secret=_WEBHOOK_SECRET)
        await adapter.send(_request())

    req = seen[0]
    signature_header = req.headers["X-AIOpsPilot-Signature"]
    timestamp_header = req.headers["X-AIOpsPilot-Timestamp"]
    assert signature_header.startswith("sha256=")
    hex_digest = signature_header.removeprefix("sha256=")
    assert len(hex_digest) == 64
    # Timestamp is a monotonic-ish unix seconds string.
    assert timestamp_header.isdigit()

    # Recompute HMAC and compare — verifies the wire signature exactly.
    mac = hmac.new(_WEBHOOK_SECRET.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp_header.encode("utf-8"))
    mac.update(b".")
    mac.update(req.content)
    expected = mac.hexdigest()
    assert hex_digest == expected


async def test_send_bot_framework_mode_attaches_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "bot-msg-1"})

    identity = StaticWorkloadIdentity(
        audience="https://api.botframework.com/.default",
        token=_BEARER,
    )
    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client, identity=identity)
        await adapter.send(_request())

    assert seen[0].headers["Authorization"] == f"Bearer {_BEARER}"
    assert "X-AIOpsPilot-Signature" not in seen[0].headers


# ---------------------------------------------------------------------------
# Card body redaction
# ---------------------------------------------------------------------------


async def test_send_refuses_card_matching_secret_pattern() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        # Embed a fake AWS access key in the blast_radius_summary; the
        # adapter MUST refuse to dispatch defense-in-depth.
        bad = _request(blast_radius_summary="leak AKIAABCDEFGHIJKLMNOP xxx")
        with pytest.raises(HilChannelError, match="secret pattern"):
            await adapter.send(bad)


async def test_send_omits_optional_fields_when_empty() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        empty_extras = _request(
            correlation_id="",
            rule_ids=(),
            reasons=(),
        )
        await adapter.send(empty_extras)

    card = json.loads(seen[0].content)["attachments"][0]["content"]
    facts = card["body"][2]["facts"]
    titles = {f["title"] for f in facts}
    # Facts skip the optional "Rules" and "Correlation" entries.
    assert "Rules" not in titles
    assert "Correlation" not in titles
    # And no **Reasons** TextBlock is appended when reasons are empty.
    reason_blocks = [
        b for b in card["body"] if isinstance(b, dict) and "Reasons" in str(b.get("text", ""))
    ]
    assert reason_blocks == []


async def test_send_includes_callback_urls_when_configured() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(
            client,
            approve_callback_url="https://api.example.com/approve",
            reject_callback_url="https://api.example.com/reject",
        )
        await adapter.send(_request())

    body = json.loads(seen[0].content)
    card = body["attachments"][0]["content"]
    approve_data = card["actions"][0]["data"]
    reject_data = card["actions"][1]["data"]
    assert approve_data["callback_url"] == "https://api.example.com/approve"
    assert reject_data["callback_url"] == "https://api.example.com/reject"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


async def test_send_4xx_raises_hil_channel_error_with_trimmed_body() -> None:
    long_body = "e" * 2000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=long_body)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(HilChannelError) as excinfo:
            await adapter.send(_request())

    err = excinfo.value
    assert err.status_code == 400
    assert err.approval_id == "appr-1"
    # Trimmed to the default 512-byte cap.
    assert "…" in str(err)
    assert "eeeee" in str(err)
    assert len(str(err)) < 2000  # not the raw 2 KB body


async def test_send_4xx_short_body_is_not_trimmed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="short error\nwith newline")

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(HilChannelError) as excinfo:
            await adapter.send(_request())

    text = str(excinfo.value)
    # Body is preserved verbatim (no truncation ellipsis), newlines
    # collapsed to spaces.
    assert "short error with newline" in text
    assert "…" not in text


async def test_send_transport_error_raises_hil_channel_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=_request)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        with pytest.raises(HilChannelError, match="send request failed"):
            await adapter.send(_request())


# ---------------------------------------------------------------------------
# poll() — P1 posture
# ---------------------------------------------------------------------------


async def test_poll_returns_pending_in_p1() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with _client(httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        receipt = HilApprovalReceipt(
            approval_id="appr-poll",
            channel_ref="teams:1",
            sent_at=datetime.now(tz=UTC),
        )
        response = await adapter.poll(receipt)

    assert response.decision is HilDecision.PENDING
    assert response.approval_id == "appr-poll"
    assert response.approver_id is None
    assert response.received_at is None


# ---------------------------------------------------------------------------
# parse_response() — approve / reject / timeout / unknown
# ---------------------------------------------------------------------------


def _base_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "approval_id": "appr-1",
        "action": "approve",
        "approver_id": "oid-abc",
        "reason": "looks good",
        "received_at": "2026-07-06T09:15:00Z",
    }
    base.update(overrides)
    return base


def test_parse_response_approve() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload())
    assert response.decision is HilDecision.APPROVE
    assert response.approval_id == "appr-1"
    assert response.approver_id == "oid-abc"
    assert response.reason == "looks good"
    assert response.received_at is not None
    assert response.received_at.tzinfo is not None
    assert response.received_at.astimezone(UTC) == datetime(2026, 7, 6, 9, 15, tzinfo=UTC)


def test_parse_response_reject() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(action="reject"))
    assert response.decision is HilDecision.REJECT


def test_parse_response_timeout() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(action="timeout"))
    assert response.decision is HilDecision.TIMEOUT


def test_parse_response_unknown_action_maps_to_pending() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(action="maybe"))
    assert response.decision is HilDecision.PENDING


def test_parse_response_case_insensitive() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(action="APPROVE"))
    assert response.decision is HilDecision.APPROVE


def test_parse_response_missing_approver_id_is_none() -> None:
    payload = _base_payload()
    payload.pop("approver_id")
    response = TeamsHilAdapter.parse_response(payload)
    assert response.approver_id is None


def test_parse_response_non_dict_raises() -> None:
    with pytest.raises(HilChannelError, match="not a JSON object"):
        TeamsHilAdapter.parse_response(["approve"])


def test_parse_response_missing_approval_id_raises() -> None:
    payload = _base_payload()
    payload.pop("approval_id")
    with pytest.raises(HilChannelError, match="missing 'approval_id'"):
        TeamsHilAdapter.parse_response(payload)


def test_parse_response_empty_approval_id_raises() -> None:
    with pytest.raises(HilChannelError, match="missing 'approval_id'"):
        TeamsHilAdapter.parse_response(_base_payload(approval_id=""))


def test_parse_response_redacts_secret_in_reason() -> None:
    payload = _base_payload(reason="here is my key ghp_" + "a" * 40)
    response = TeamsHilAdapter.parse_response(payload)
    assert response.reason == "[redacted]"


def test_parse_response_empty_reason_becomes_none() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(reason=""))
    assert response.reason is None


def test_parse_response_bad_timestamp_is_none() -> None:
    response = TeamsHilAdapter.parse_response(_base_payload(received_at="not-a-date"))
    assert response.received_at is None


def test_parse_response_missing_timestamp_is_none() -> None:
    payload = _base_payload()
    payload.pop("received_at")
    response = TeamsHilAdapter.parse_response(payload)
    assert response.received_at is None


def test_parse_response_missing_action_maps_to_pending() -> None:
    payload = _base_payload()
    payload.pop("action")
    response = TeamsHilAdapter.parse_response(payload)
    assert response.decision is HilDecision.PENDING
