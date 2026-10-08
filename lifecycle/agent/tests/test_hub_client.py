from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from fdai_lifecycle_agent.hub_client import (
    MAX_CONCURRENT_WRITE_RETRIES,
    MAX_PLAN_RESPONSE_BYTES,
    HttpHubClient,
    HubProtocolError,
    PlanReport,
    SignedPlan,
    validate_hub_url,
)

HUB = "http://127.0.0.1:8740"


def _client(handler: httpx.MockTransport, sleeps: list[float] | None = None) -> HttpHubClient:
    recorded = sleeps if sleeps is not None else []
    return HttpHubClient(HUB, transport=handler, sleep=recorded.append)


def _plan_body(**plan: object) -> bytes:
    return json.dumps({"plan": plan}).encode()


def _report(**overrides: Any) -> PlanReport:
    report = PlanReport(
        attempt=1,
        outcome="dry-run-admitted",
        reason_code="dry_run_computed",
        exact_plan_digest="sha256:" + "a" * 64,
        summary='{"entity_count":1}',
        reported_at=datetime(2026, 10, 7, 21, 0, tzinfo=UTC),
    )
    return replace(report, **overrides)


def test_fetch_plan_decodes_base64_fields_from_contract_path() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(
            200,
            content=_plan_body(
                signed_payload=base64.b64encode(b"payload").decode(),
                signature=base64.b64encode(b"signature").decode(),
            ),
        )

    with _client(httpx.MockTransport(handler)) as client:
        plan = client.fetch_plan("installation-alpha")

    assert plan == SignedPlan(b"payload", b"signature")
    assert seen == ["GET /v1/installations/installation-alpha/plan"]


def test_fetch_plan_returns_none_for_no_content() -> None:
    with _client(httpx.MockTransport(lambda request: httpx.Response(204))) as client:
        assert client.fetch_plan("installation-alpha") is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500), "returned 500"),
        (httpx.Response(404, json={"error": "not_found"}), "does not know this installation"),
        (httpx.Response(302, headers={"location": "https://elsewhere.test/"}), "returned 302"),
        (httpx.Response(200, content=b"not json"), "not JSON"),
        (httpx.Response(200, content=b"[]"), "only a plan object"),
        (httpx.Response(200, content=_plan_body(signed_payload="cA==")), "only signed_payload"),
        (
            httpx.Response(200, content=_plan_body(signed_payload="***", signature="cA==")),
            "not valid base64",
        ),
        (
            httpx.Response(200, content=_plan_body(signed_payload="", signature="cA==")),
            "non-empty base64",
        ),
        (httpx.Response(200, content=b"x" * (MAX_PLAN_RESPONSE_BYTES + 1)), "size limit"),
    ],
)
def test_fetch_plan_rejects_responses_outside_contract(
    response: httpx.Response, message: str
) -> None:
    with (
        _client(httpx.MockTransport(lambda request: response)) as client,
        pytest.raises(HubProtocolError, match=message),
    ):
        client.fetch_plan("installation-alpha")


def test_fetch_plan_wraps_transport_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with (
        _client(httpx.MockTransport(handler)) as client,
        pytest.raises(HubProtocolError, match="ConnectError"),
    ):
        client.fetch_plan("installation-alpha")


def test_submit_report_posts_contract_body() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(202)

    with _client(httpx.MockTransport(handler)) as client:
        client.submit_report("installation-alpha", "plan-0008", _report())

    assert seen == [
        (
            "/v1/installations/installation-alpha/plans/plan-0008/reports",
            {
                "attempt": 1,
                "outcome": "dry-run-admitted",
                "reason_code": "dry_run_computed",
                "exact_plan_digest": "sha256:" + "a" * 64,
                "summary": '{"entity_count":1}',
                "reported_at": "2026-10-07T21:00:00Z",
            },
        )
    ]


@pytest.mark.parametrize(
    ("response", "message", "code"),
    [
        (httpx.Response(200), "returned 200$", ""),
        (httpx.Response(409, json={"error": "report_conflict"}), "409", "report_conflict"),
        (
            httpx.Response(409, json={"error": "plan_digest_mismatch"}),
            "409",
            "plan_digest_mismatch",
        ),
        (httpx.Response(422, json={"error": "report_invalid"}), "422", "report_invalid"),
        (httpx.Response(404, json={"error": "not_found"}), "404", "not_found"),
        (httpx.Response(409, json={"error": "Secret Value"}), "returned 409$", ""),
        (httpx.Response(409, content=b"not json"), "returned 409$", ""),
    ],
)
def test_submit_report_requires_accepted_status(
    response: httpx.Response, message: str, code: str
) -> None:
    with (
        _client(httpx.MockTransport(lambda request: response)) as client,
        pytest.raises(HubProtocolError, match=message) as raised,
    ):
        client.submit_report("installation-alpha", "plan-0008", _report())

    assert raised.value.code == code


def test_submit_report_retries_the_same_report_after_concurrent_write() -> None:
    bodies: list[bytes] = []
    statuses = iter([503, 503, 202])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        status = next(statuses)
        if status == 503:
            return httpx.Response(
                503, headers={"Retry-After": "1"}, json={"error": "concurrent_write"}
            )
        return httpx.Response(status)

    with _client(httpx.MockTransport(handler), sleeps) as client:
        client.submit_report("installation-alpha", "plan-0008", _report())

    assert len(bodies) == 3
    assert len(set(bodies)) == 1
    assert sleeps == [1.0, 1.0]


@pytest.mark.parametrize(
    "body", [{"error": "service_unavailable"}, None], ids=["other-code", "no-code"]
)
def test_other_503_is_left_for_the_next_poll_without_waiting(body: dict[str, str] | None) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, headers={"Retry-After": "1"}, json=body)

    with (
        _client(httpx.MockTransport(handler), sleeps) as client,
        pytest.raises(HubProtocolError, match="returned 503"),
    ):
        client.submit_report("installation-alpha", "plan-0008", _report())

    assert (len(calls), sleeps) == (1, [])


def test_submit_report_gives_up_after_bounded_concurrent_write_retries() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            503, headers={"Retry-After": "600"}, json={"error": "concurrent_write"}
        )

    with (
        _client(httpx.MockTransport(handler), sleeps) as client,
        pytest.raises(HubProtocolError, match="503 concurrent_write"),
    ):
        client.submit_report("installation-alpha", "plan-0008", _report())

    assert len(calls) == MAX_CONCURRENT_WRITE_RETRIES + 1
    assert sleeps == [5.0] * MAX_CONCURRENT_WRITE_RETRIES


@pytest.mark.parametrize("plan_id", ["../admin", "plan/0008", "", "plan 8"])
def test_unsafe_path_segments_are_refused(plan_id: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent")

    with (
        _client(httpx.MockTransport(handler)) as client,
        pytest.raises(HubProtocolError, match="safe path segment"),
    ):
        client.submit_report("installation-alpha", plan_id, _report())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"exact_plan_digest": None}, "MUST name exact_plan_digest"),
        ({"reason_code": "Plan-Expired"}, "reason_code MUST match"),
        ({"reason_code": "a" * 97}, "reason_code MUST match"),
        ({"summary": "x" * 2001}, "at most 2000 characters"),
        ({"reported_at": datetime(2026, 10, 7)}, "timezone"),
    ],
)
def test_report_rejects_what_the_hub_would_refuse(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _report(**overrides)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8740", "http://localhost:8740/", "http://[::1]:8740", "https://hub.test"],
)
def test_hub_url_accepts_https_or_loopback_http(url: str) -> None:
    assert validate_hub_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://hub.test",
        "http://10.0.0.4:8740",
        "ftp://127.0.0.1",
        "https://user:pass@hub.test",
        "https://hub.test/?x=1",
        "https://",
    ],
)
def test_hub_url_refuses_remote_plain_http_and_credentials(url: str) -> None:
    with pytest.raises(ValueError, match="Hub URL"):
        validate_hub_url(url)
