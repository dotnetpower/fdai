"""No-network Slack card click through Operator's one-use browser decision."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from fdai.delivery.chatops.slack_adapter import (
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.shared.providers.hil_channel import HilApprovalRequest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.iam.contracts import (
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    HilCallbackAuthorityConfig,
)
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.slack_handoff import (
    make_slack_handoff_routes,
    verify_slack_click,
)
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
SIGNING_SECRET = "synthetic-signing-key"
CHANNEL_ID = "CEXAMPLE1"
TEAM_ID = "TEXAMPLE1"
APPROVAL_ID = "approval-1"


def _approval(dispatch_id: str) -> HilApprovalRequest:
    return HilApprovalRequest(
        approval_id=APPROVAL_ID,
        correlation_id="correlation-1",
        action_id="action-1",
        action_type="action.example",
        rule_ids=(),
        target_resource_ref="example-resource",
        blast_radius_summary="one resource",
        action_hash="action-hash-1",
        metadata={"idempotency_key": "idem-1", "approval_dispatch_id": dispatch_id},
    )


class HandoffStore:
    def __init__(self) -> None:
        self.clicks: set[str] = set()
        self.records: dict[str, dict[str, object]] = {}

    async def create_click(self, digest: str) -> bool:
        if digest in self.clicks:
            return False
        self.clicks.add(digest)
        return True

    async def put(self, digest: str, record: dict[str, object]) -> None:
        self.records[digest] = record

    async def read(self, digest: str) -> dict[str, object] | None:
        return self.records.get(digest)

    async def consume(self, digest: str) -> bool:
        record = self.records.get(digest)
        if record is None or record["consumed"]:
            return False
        record["consumed"] = True
        return True


class Registry:
    def __init__(self) -> None:
        self.context = HilCallbackContext(
            approval_id=APPROVAL_ID,
            correlation_id="correlation-1",
            idempotency_key="idem-1",
            action_hash="action-hash-1",
            expires_at=NOW + timedelta(minutes=10),
            submitter_oid="submitter-1",
            metadata={"decision_route": "action"},
        )
        self.command: HilDecisionCommand | None = None
        self.receipt: HilDecisionReceipt | None = None

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        return self.context if approval_id == APPROVAL_ID else None

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None:
        return self.receipt if approval_id == APPROVAL_ID else None

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        self.command = command
        self.receipt = HilDecisionReceipt(
            approval_id=APPROVAL_ID,
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref="synthetic-receipt",
            justification=command.justification,
        )
        return self.receipt

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        self.receipt = replace(receipt, delivered=True)
        return self.receipt


class Audit:
    async def append_callback_audit(self, record: object) -> None:
        return None


class Outbox:
    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        return None


def _client(
    store: HandoffStore,
    registry: Registry,
    clock: list[datetime],
    *,
    mapping: dict[str, str] | None = None,
) -> TestClient:
    config = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_SLACK_TEAM_ID": TEAM_ID,
            "FDAI_SLACK_PRINCIPAL_MAP_JSON": json.dumps(
                mapping if mapping is not None else {"slack-user": "approver-1"}
            ),
        },
        group_ids={role: f"group-{role.value}" for role in OperatorRole},
    )

    def verifier(token: str) -> dict[str, object]:
        return {
            "oid": "wrong-actor" if token == "wrong" else "approver-1",
            "idtyp": "user",
            "roles": ["Approver"],
            "auth_time": int((NOW if token == "stale" else NOW + timedelta(seconds=2)).timestamp()),
        }

    return TestClient(
        Starlette(
            routes=make_slack_handoff_routes(
                store=store,  # type: ignore[arg-type] - isolated CAS double.
                signing_secret=SIGNING_SECRET,
                config=config,
                authenticator=OperatorAuthenticator(verifier=verifier, group_ids={}),
                registry=registry,
                outbox=Outbox(),
                audit=Audit(),
                context_reader=registry,
                console_origin="http://localhost:5273",
                clock=lambda: clock[0],
            )
        )
    )


def _signed_action(action: dict[str, object], *, trigger: str) -> tuple[bytes, dict[str, str]]:
    payload = {
        "type": "block_actions",
        "team": {"id": TEAM_ID},
        "user": {"id": "slack-user"},
        "trigger_id": trigger,
        "actions": [action],
    }
    raw = urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode()
    stamp = str(int(NOW.timestamp()))
    signature = hmac.new(
        SIGNING_SECRET.encode(), b"v0:" + stamp.encode() + b":" + raw, hashlib.sha256
    ).hexdigest()
    return raw, {
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": f"v0={signature}",
    }


@pytest.mark.parametrize(("button_index", "decision"), [(0, "approve"), (1, "reject")])
async def test_rendered_slack_action_requires_fresh_browser_actor(
    button_index: int,
    decision: str,
) -> None:
    posts: list[bytes] = []

    def post(request: httpx.Request) -> httpx.Response:
        posts.append(request.content)
        return httpx.Response(200, json={"ok": True, "channel": CHANNEL_ID, "ts": "123.456"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(post)) as http_client:
        adapter = SlackHilAdapter(
            config=SlackHilAdapterConfig(
                api_url=SLACK_POST_URL, channel_id=CHANNEL_ID, bot_token="synthetic-token"
            ),
            http_client=http_client,
        )
        first = _approval("reminder-1")
        second = _approval("reminder-2")
        assert (
            hashlib.sha256(adapter.render_payload(first)).digest()
            != hashlib.sha256(adapter.render_payload(second)).digest()
        )
        await adapter.send(first)
    assert len(posts) == 1
    rendered = json.loads(posts[0])
    assert "approval_dispatch_id: reminder-1" in posts[0].decode()
    buttons = rendered["blocks"][-1]["elements"]
    assert [button["action_id"] for button in buttons] == [
        "fdai_hil_approve",
        "fdai_hil_reject",
    ]
    assert all(button["value"] == APPROVAL_ID for button in buttons)
    assert all(set(button) == {"type", "text", "action_id", "value"} for button in buttons)
    assert all(
        value not in posts[0].decode()
        for value in ("approver_oid", "actor_role", "execution_authority", "action_hash")
    )

    raw, headers = _signed_action(buttons[button_index], trigger="click-1")
    click = verify_slack_click(raw, headers, secret=SIGNING_SECRET, workspace=TEAM_ID, now=NOW)
    assert click.approval_id == APPROVAL_ID
    assert click.decision.value == decision
    store, registry, clock = HandoffStore(), Registry(), [NOW]
    client = _client(store, registry, clock)
    received = client.post("/hil/slack/interaction", content=raw, headers=headers)
    assert received.status_code == 200
    url = received.json()["text"].split()[-1]
    assert urlsplit(url).netloc == "localhost:5273"
    assert urlsplit(url).path == "/approvals"
    token = parse_qs(urlsplit(url).query)["handoff"][0]
    assert token not in repr(store.records)
    assert list(store.records.values())[0]["expires_at"] == (NOW + timedelta(minutes=5)).isoformat()
    assert client.post("/hil/slack/interaction", content=raw, headers=headers).status_code == 409

    clock[0] = NOW + timedelta(seconds=2)
    route = f"/hil/slack/handoff/{token}"
    assert client.get(route, headers={"authorization": "Bearer fresh"}).json() == {
        "approval_id": APPROVAL_ID,
        "decision": decision,
    }
    for bearer in ("wrong", "stale"):
        denied = client.post(
            route,
            headers={"authorization": f"Bearer {bearer}"},
            json={"justification": "independent review"},
        )
        assert denied.status_code == 403
        assert registry.command is None
        assert list(store.records.values())[0]["consumed"] is False
    changed = _client(store, registry, clock, mapping={"slack-user": "different-actor"})
    assert changed.get(route, headers={"authorization": "Bearer fresh"}).status_code == 409
    decided = client.post(
        route,
        headers={"authorization": "Bearer fresh"},
        json={"justification": "independent review"},
    )
    assert decided.status_code in (200, 202)
    assert registry.command is not None
    assert registry.command.decision.value == decision
    assert registry.command.approver_oid == "approver-1"
    assert (
        client.post(
            route,
            headers={"authorization": "Bearer fresh"},
            json={"justification": "independent review"},
        ).status_code
        == 410
    )
