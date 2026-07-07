"""Wave W1.3 - HIL callback POST route (opt-in, HMAC-authenticated)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from aiopspilot.delivery.read_api.auth import build_authenticator
from aiopspilot.delivery.read_api.hil_callback import (
    HilCallbackConfig,
)
from aiopspilot.delivery.read_api.main import ReadApiConfig, build_app
from aiopspilot.delivery.read_api.read_model import InMemoryConsoleReadModel
from aiopspilot.shared.providers.hil_registry import HilPendingItem
from aiopspilot.shared.providers.testing.hil_registry import InMemoryHilApprovalRegistry

SECRET = "shared-secret-for-tests"


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(body)
    return f"sha256={mac.hexdigest()}"


def _pending(
    *,
    approval_id: str = "appr-1",
    idempotency_key: str = "idem-1",
    submitter_oid: str = "user-submitter",
) -> HilPendingItem:
    return HilPendingItem(
        idempotency_key=idempotency_key,
        approval_id=approval_id,
        event_id="e-1",
        action_id="a-1",
        action_kind="remediate.tag-add",
        target_resource_ref="rg/vm-a",
        reason="short",
        submitter_oid=submitter_oid,
    )


def _build_app_with_callback(
    registry: InMemoryHilApprovalRegistry,
    *,
    now: datetime | None = None,
) -> object:
    del now  # composition-root wiring uses the default clock
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    return build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            hil_callback=HilCallbackConfig(secret=SECRET),
            hil_registry=registry,
        ),
    )


# ---------------------------------------------------------------------------
# Config invariants
# ---------------------------------------------------------------------------


def test_config_secret_required() -> None:
    with pytest.raises(ValueError, match="secret"):
        HilCallbackConfig(secret="")


def test_config_max_skew_positive() -> None:
    with pytest.raises(ValueError, match="max_skew_seconds"):
        HilCallbackConfig(secret=SECRET, max_skew_seconds=0)


def test_config_max_body_positive() -> None:
    with pytest.raises(ValueError, match="max_body_bytes"):
        HilCallbackConfig(secret=SECRET, max_body_bytes=0)


def test_app_factory_fails_fast_when_callback_set_without_registry() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    with pytest.raises(ValueError, match="hil_registry"):
        build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=ReadApiConfig(
                hil_callback=HilCallbackConfig(secret=SECRET),
                hil_registry=None,
            ),
        )


def test_callback_route_only_registered_when_config_set() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app_without = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(),
    )
    paths = {r.path for r in app_without.routes if hasattr(r, "path")}
    assert not any("/hil/" in p and "/decision" in p for p in paths)

    registry = InMemoryHilApprovalRegistry()
    app_with = _build_app_with_callback(registry)
    paths_with = {r.path for r in app_with.routes if hasattr(r, "path")}
    assert "/hil/{approval_id}/decision" in paths_with


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_approve_records_decision_via_registry() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(approval_id="appr-1", submitter_oid="user-sub")])
    app = _build_app_with_callback(registry)
    client = TestClient(app)

    body_payload = {
        "decision": "approve",
        "actor_oid": "user-approver",
        "justification": "reviewed and approved by on-call",
    }
    body = json.dumps(body_payload).encode()
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "x-aiopspilot-timestamp": timestamp,
        "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
        "content-type": "application/json",
    }
    response = client.post("/hil/appr-1/decision", content=body, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decision"] == "approve"
    assert payload["approval_id"] == "appr-1"
    assert payload["already_recorded"] is False


def test_second_call_after_resolution_returns_404() -> None:
    """Once the approval is resolved, the pending item disappears from
    the registry and subsequent callbacks to the same approval_id
    return 404 - the approval is single-use, fail-closed."""

    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {
            "decision": "approve",
            "actor_oid": "user-approver",
            "justification": "reviewed and approved by on-call",
        }
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "x-aiopspilot-timestamp": timestamp,
        "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
        "content-type": "application/json",
    }

    r1 = client.post("/hil/appr-1/decision", content=body, headers=headers)
    r2 = client.post("/hil/appr-1/decision", content=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# HMAC / replay
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "approve", "actor_oid": "u", "justification": "x"}).encode()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401


def test_bad_hmac_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reason of some length ok"}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": "sha256=deadbeef",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["kind"] == "unauthorized"


def test_replay_window_enforced() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reason of some length ok"}
    ).encode()
    # Timestamp two hours in the past exceeds default 300s window.
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": old,
            "x-aiopspilot-signature": _sign(SECRET, old, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401
    assert "skew" in response.json()["error"]["message"].lower()


def test_signature_wrong_algorithm_prefix_returns_401() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{}"
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": "md5=deadbeef",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401


def test_naive_timestamp_rejected() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{}"
    naive_ts = "2026-07-07T00:00:00"  # no tz offset
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": naive_ts,
            "x-aiopspilot-signature": _sign(SECRET, naive_ts, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


def test_bad_json_body_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = b"{not json"
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_unknown_decision_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "escalate", "actor_oid": "u", "justification": "x"}).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_missing_actor_oid_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps({"decision": "approve"}).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


def test_body_too_large_returns_400() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending()])
    # Custom config with very small body cap.
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            hil_callback=HilCallbackConfig(secret=SECRET, max_body_bytes=20),
            hil_registry=registry,
        ),
    )
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "x" * 100}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# no_self_approval + not-found
# ---------------------------------------------------------------------------


def test_self_approval_is_403() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(submitter_oid="same-user")])
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {
            "decision": "approve",
            "actor_oid": "same-user",  # equals submitter_oid -> refused
            "justification": "reviewed and approved by on-call",
        }
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/appr-1/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["kind"] == "self_approval_forbidden"


def test_unknown_approval_id_is_404() -> None:
    registry = InMemoryHilApprovalRegistry()
    # Nothing seeded.
    app = _build_app_with_callback(registry)
    client = TestClient(app)
    body = json.dumps(
        {"decision": "approve", "actor_oid": "u", "justification": "reviewed and approved"}
    ).encode()
    timestamp = datetime.now(UTC).isoformat()
    response = client.post(
        "/hil/missing/decision",
        content=body,
        headers={
            "x-aiopspilot-timestamp": timestamp,
            "x-aiopspilot-signature": _sign(SECRET, timestamp, body),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 404
