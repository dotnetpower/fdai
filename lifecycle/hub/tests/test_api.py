from __future__ import annotations

from base64 import b64decode
from collections.abc import Iterator
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import MAX_REPORT_BYTES, create_app
from fdai_lifecycle_hub.domain import Installation, Issued, IssuedPlan, Planner
from fdai_lifecycle_hub.signing import HubSigningKey, signature_verifier
from fdai_lifecycle_hub.store import HubStore

REPORT: dict[str, object] = {
    "attempt": 1,
    "outcome": "dry-run-admitted",
    "reason_code": "admitted",
    "summary": "dry run admitted",
    "reported_at": "2026-10-05T03:01:00Z",
}


@pytest.fixture
def client(store: HubStore, installation: Installation, now: datetime) -> TestClient:
    store.register(installation, now=now)
    return TestClient(create_app(store, clock=lambda: now))


@pytest.fixture
def issued(store: HubStore, installation: Installation, planner: Planner, now: datetime) -> Issued:
    outcome = store.recompute(installation.installation_id, planner, now=now)
    assert isinstance(outcome, Issued)
    return outcome


@pytest.fixture
def report(issued: Issued) -> dict[str, object]:
    return REPORT | {"exact_plan_digest": IssuedPlan.from_signed(issued.plan).digest}


def _reports_url(plan_id: str) -> str:
    return f"/v1/installations/installation-alpha/plans/{plan_id}/reports"


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_no_plan_returns_204(client: TestClient) -> None:
    assert client.get("/v1/installations/installation-alpha/plan").status_code == 204


def test_unknown_installation_returns_404(client: TestClient) -> None:
    response = client.get("/v1/installations/missing/plan")

    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_plan_is_served_as_verifiable_signed_bytes(
    client: TestClient, issued: Issued, key: HubSigningKey
) -> None:
    response = client.get("/v1/installations/installation-alpha/plan")

    assert response.status_code == 200
    body = response.json()["plan"]
    payload, signature = b64decode(body["signed_payload"]), b64decode(body["signature"])
    assert payload == issued.plan.signed_payload
    assert signature_verifier({key.key_id: key.public_key})(key.key_id, payload, signature)


def test_report_is_accepted_once_and_conflicts_are_rejected(
    client: TestClient, issued: Issued, report: dict[str, object]
) -> None:
    url = _reports_url(issued.plan.plan_id)

    assert client.post(url, json=report).status_code == 202
    assert client.post(url, json=report).status_code == 202
    conflict = client.post(url, json=report | {"outcome": "rejected"})
    assert (conflict.status_code, conflict.json()) == (409, {"error": "report_conflict"})


def test_report_naming_other_plan_bytes_returns_409(
    client: TestClient, issued: Issued, report: dict[str, object]
) -> None:
    body = report | {"exact_plan_digest": "sha256:" + "d" * 64}

    response = client.post(_reports_url(issued.plan.plan_id), json=body)

    assert (response.status_code, response.json()) == (409, {"error": "plan_digest_mismatch"})


@pytest.mark.parametrize(
    "change",
    [
        {"attempt": 0},
        {"outcome": "applied"},
        {"exact_plan_digest": "sha256:short"},
        {"exact_plan_digest": None},
        {"reported_at": "2026-10-05T03:01:00"},
        {"unexpected": True},
    ],
)
def test_invalid_report_returns_422(
    client: TestClient, issued: Issued, report: dict[str, object], change: dict[str, object]
) -> None:
    response = client.post(_reports_url(issued.plan.plan_id), json=report | change)

    assert (response.status_code, response.json()) == (422, {"error": "report_invalid"})


def test_oversized_report_returns_413(client: TestClient, issued: Issued) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * MAX_REPORT_BYTES
        yield b"x"

    response = client.post(_reports_url(issued.plan.plan_id), content=chunks())

    assert (response.status_code, response.json()) == (413, {"error": "report_too_large"})


def test_report_for_unknown_plan_returns_404(client: TestClient, report: dict[str, object]) -> None:
    assert client.post(_reports_url("missing"), json=report).status_code == 404
