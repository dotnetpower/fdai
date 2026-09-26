"""Signed Slack click and one-use browser handoff safety regressions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import fdai_operator_service.families.iam.slack_handoff as handoff_module
import pytest
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
    PostgresSlackHandoffStore,
    make_slack_handoff_routes,
    verify_slack_click,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreConfig
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
SECRET = "synthetic-slack-signature-key"
GROUPS = {role: f"group-{role.value}" for role in OperatorRole}


class RecordingHilRegistry:
    def __init__(self) -> None:
        self.context = HilCallbackContext(
            approval_id="approval-1",
            correlation_id="correlation-1",
            idempotency_key="hil-key-1",
            action_hash="action-hash-1",
            expires_at=NOW + timedelta(minutes=10),
            submitter_oid="submitter-1",
            metadata={"decision_route": "action"},
        )
        self.command: HilDecisionCommand | None = None
        self.receipt: HilDecisionReceipt | None = None

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        return self.context if approval_id == self.context.approval_id else None

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None:
        return self.receipt if approval_id == self.context.approval_id else None

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        self.command = command
        self.receipt = HilDecisionReceipt(
            approval_id=command.approval_id,
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


class RecordingHilAudit:
    async def append_callback_audit(self, record: object) -> None:
        return None


class RecordingHilOutbox:
    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        return None


class MemoryHandoffStore:
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


def _signed(
    *,
    sender: str = "slack-user",
    team: str = "slack-team",
    decision: str = "fdai_hil_approve",
    approval: str = "approval-1",
    trigger: str = "trigger-1",
    timestamp: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    payload = {
        "type": "block_actions",
        "team": {"id": team},
        "user": {"id": sender},
        "trigger_id": trigger,
        "actions": [{"action_id": decision, "value": approval}],
    }
    raw = urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode()
    ts = str(timestamp if timestamp is not None else int(NOW.timestamp()))
    signature = (
        "v0="
        + hmac.new(SECRET.encode(), b"v0:" + ts.encode() + b":" + raw, hashlib.sha256).hexdigest()
    )
    return raw, {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": signature,
        "content-type": "application/x-www-form-urlencoded",
    }


def _client(
    store: MemoryHandoffStore,
    registry: RecordingHilRegistry,
    *,
    mapping: dict[str, str] | None = None,
    oid: str = "approver-1",
    roles: list[str] | None = None,
    auth_time: int | None = None,
) -> TestClient:
    config = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_SLACK_TEAM_ID": "slack-team",
            "FDAI_SLACK_PRINCIPAL_MAP_JSON": json.dumps(
                mapping if mapping is not None else {"slack-user": "approver-1"}
            ),
        },
        group_ids=GROUPS,
    )
    claims: dict[str, object] = {
        "oid": oid,
        "idtyp": "user",
        "roles": roles if roles is not None else ["Approver"],
    }
    if auth_time is not None:
        claims["auth_time"] = auth_time
    verifier = OperatorAuthenticator(verifier=lambda _: claims, group_ids={})
    return TestClient(
        Starlette(
            routes=make_slack_handoff_routes(
                store=store,  # type: ignore[arg-type] - in-memory CAS double.
                signing_secret=SECRET,
                config=config,
                authenticator=verifier,
                registry=registry,
                outbox=RecordingHilOutbox(),
                audit=RecordingHilAudit(),
                context_reader=registry,
                console_origin="http://localhost:5273",
                clock=lambda: NOW,
            )
        )
    )


def _mint(client: TestClient, *, trigger: str = "trigger-1") -> str:
    raw, headers = _signed(trigger=trigger)
    response = client.post("/hil/slack/interaction", content=raw, headers=headers)
    assert response.status_code == 200, response.text
    text = response.json()["text"]
    url = text.split()[-1]
    return parse_qs(urlsplit(url).query)["handoff"][0]


def test_signature_over_exact_raw_body_replay_window_and_actor() -> None:
    raw, headers = _signed()
    click = verify_slack_click(raw, headers, secret=SECRET, workspace="slack-team", now=NOW)
    assert click.sender == "slack-user"
    assert click.decision.value == "approve"
    with pytest.raises(ValueError, match="signature"):
        verify_slack_click(raw + b" ", headers, secret=SECRET, workspace="slack-team", now=NOW)
    with pytest.raises(ValueError, match="replay"):
        verify_slack_click(
            raw, headers, secret=SECRET, workspace="slack-team", now=NOW + timedelta(minutes=6)
        )
    other, signed_other = _signed(team="another-team")
    with pytest.raises(ValueError, match="workspace"):
        verify_slack_click(other, signed_other, secret=SECRET, workspace="slack-team", now=NOW)


def test_verified_click_mints_only_digest_and_consumes_before_one_decision() -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    registry.context = registry.context.__class__(
        approval_id="approval-1",
        correlation_id="correlation-1",
        idempotency_key="hil-key-1",
        action_hash="action-hash-1",
        expires_at=NOW + timedelta(minutes=10),
        submitter_oid="submitter-1",
        metadata={"decision_route": "action"},
    )
    client = _client(store, registry, auth_time=int(NOW.timestamp()) + 1)
    token = _mint(client)
    assert token not in repr(store.records)
    assert list(store.records.values())[0]["mapping_revision"]
    headers = {"authorization": "Bearer synthetic"}
    preview = client.get(f"/hil/slack/handoff/{token}", headers=headers)
    assert preview.json() == {"approval_id": "approval-1", "decision": "approve"}
    denied = client.post(
        f"/hil/slack/handoff/{token}",
        headers=headers,
        json={
            "decision": "reject",
            "justification": "different browser decision",
        },
    )
    assert denied.status_code == 400
    result = client.post(
        f"/hil/slack/handoff/{token}", headers=headers, json={"justification": "checked rollback"}
    )
    assert result.status_code in (200, 202)
    assert registry.command is not None
    assert registry.command.approver_oid == "approver-1"
    assert registry.command.decision.value == "approve"
    assert (
        client.post(
            f"/hil/slack/handoff/{token}",
            headers=headers,
            json={"justification": "checked rollback"},
        ).status_code
        == 410
    )
    raw, signed = _signed()
    assert client.post("/hil/slack/interaction", content=raw, headers=signed).status_code == 409


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"auth_time": None}, 403),
        ({"auth_time": int(NOW.timestamp())}, 403),
        ({"auth_time": int((NOW - timedelta(minutes=1)).timestamp())}, 403),
        ({"oid": "wrong-actor"}, 403),
        ({"roles": ["Reader"]}, 403),
    ],
)
def test_unproven_or_wrong_actor_never_consumes(change: dict[str, object], expected: int) -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    registry.context = registry.context.__class__(
        approval_id="approval-1",
        correlation_id="correlation-1",
        idempotency_key="hil-key-1",
        action_hash="action-hash-1",
        expires_at=NOW + timedelta(minutes=10),
        submitter_oid="submitter-1",
        metadata={"decision_route": "action"},
    )
    good = _client(store, registry, auth_time=int(NOW.timestamp()) + 1)
    token = _mint(good)
    bad = _client(store, registry, **change)  # type: ignore[arg-type]
    assert (
        bad.post(
            f"/hil/slack/handoff/{token}",
            headers={"authorization": "Bearer synthetic"},
            json={"justification": "reviewed"},
        ).status_code
        == expected
    )
    assert registry.command is None
    assert list(store.records.values())[0]["consumed"] is False


def test_changed_mapping_or_park_and_expiry_fail_closed() -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    registry.context = registry.context.__class__(
        approval_id="approval-1",
        correlation_id="correlation-1",
        idempotency_key="hil-key-1",
        action_hash="action-hash-1",
        expires_at=NOW + timedelta(minutes=10),
        submitter_oid="submitter-1",
        metadata={"decision_route": "action"},
    )
    good = _client(store, registry)
    token = _mint(good)
    path = f"/hil/slack/handoff/{token}"
    assert (
        _client(store, registry, mapping={"slack-user": "other-oid"})
        .get(path, headers={"authorization": "Bearer synthetic"})
        .status_code
        == 409
    )
    registry.context = registry.context.__class__(
        approval_id="approval-1",
        correlation_id="correlation-1",
        idempotency_key="hil-key-1",
        action_hash="different-action",
        expires_at=NOW + timedelta(minutes=10),
        submitter_oid="submitter-1",
        metadata={"decision_route": "action"},
    )
    assert good.get(path, headers={"authorization": "Bearer synthetic"}).status_code == 409
    list(store.records.values())[0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    assert good.get(path, headers={"authorization": "Bearer synthetic"}).status_code == 410


def test_unmapped_actor_and_expired_park_never_mint_handoff() -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    raw, headers = _signed()
    unknown = _client(store, registry, mapping={"another-user": "approver-1"})
    assert unknown.post("/hil/slack/interaction", content=raw, headers=headers).status_code == 403
    assert not store.records
    registry.context = replace(registry.context, expires_at=NOW - timedelta(seconds=1))
    configured = _client(store, registry)
    assert (
        configured.post("/hil/slack/interaction", content=raw, headers=headers).status_code == 410
    )
    assert not store.records


def test_self_approval_is_denied_after_nonce_claim() -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    registry.context = replace(registry.context, submitter_oid="approver-1")
    client = _client(store, registry, auth_time=int(NOW.timestamp()) + 1)
    token = _mint(client)
    result = client.post(
        f"/hil/slack/handoff/{token}",
        headers={"authorization": "Bearer synthetic"},
        json={"justification": "checked rollback"},
    )
    assert result.status_code == 403
    assert registry.command is None


def test_distinct_reordered_clicks_cannot_change_recorded_decision() -> None:
    store, registry = MemoryHandoffStore(), RecordingHilRegistry()
    client = _client(store, registry, auth_time=int(NOW.timestamp()) + 1)
    first = _mint(client)
    second = _mint(client, trigger="trigger-2")
    path = f"/hil/slack/handoff/{first}"
    headers = {"authorization": "Bearer synthetic"}
    assert client.post(
        path, headers=headers, json={"justification": "checked rollback"}
    ).status_code in (200, 202)
    assert (
        client.post(
            f"/hil/slack/handoff/{second}", headers=headers, json={"justification": "changed"}
        ).status_code
        == 409
    )
    assert registry.command is not None and registry.command.justification == "checked rollback"


def test_two_claims_for_same_nonce_are_exclusive() -> None:
    store = MemoryHandoffStore()
    digest = hashlib.sha256(b"synthetic-nonce").hexdigest()
    store.records[digest] = {"consumed": False}

    async def race() -> tuple[bool, bool]:
        first, second = await asyncio.gather(store.consume(digest), store.consume(digest))
        return first, second

    first, second = asyncio.run(race())
    assert sorted((first, second)) == [False, True]


def test_postgres_nonce_claim_uses_atomic_conditional_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[tuple[str, tuple[object, ...]]] = []
    consumed = False

    class Connection:
        async def __aenter__(self) -> Connection:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def transaction(self) -> Connection:
            return self

        async def execute(self, statement: str, parameters: tuple[object, ...]) -> Connection:
            statements.append((statement, parameters))
            return self

        async def fetchone(self) -> tuple[str] | None:
            nonlocal consumed
            if consumed:
                return None
            consumed = True
            return ("operator-slack-handoff:synthetic",)

    class ConnectionFactory:
        @staticmethod
        async def connect(*_: object, **__: object) -> Connection:
            return Connection()

    monkeypatch.setattr(handoff_module, "AsyncConnection", ConnectionFactory)
    store = PostgresSlackHandoffStore(PostgresFamilyStoreConfig(dsn="postgresql://localhost/fdai"))

    async def claim_twice() -> tuple[bool, bool]:
        return await store.consume("synthetic"), await store.consume("synthetic")

    assert asyncio.run(claim_twice()) == (True, False)
    claims = [entry for entry in statements if "UPDATE state_kv" in entry[0]]
    assert len(claims) == 2
    assert all("value->>'consumed' = 'false'" in statement for statement, _ in claims)
    assert all(
        "(value->>'expires_at')::timestamptz > NOW()" in statement for statement, _ in claims
    )
    assert all(parameters == ("operator-slack-handoff:synthetic",) for _, parameters in claims)
