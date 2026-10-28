from __future__ import annotations

import base64
import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native import NativeApproval, NativeScope
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    NativeScopeTransitionCompletion,
    NativeScopeTransitionCompletionReceipt,
    NativeScopeTransitionReceipt,
    NativeScopeTransitionReportedState,
    NativeScopeTransitionRequest,
    existing_resources_digest,
    hub_key_id,
    sign_transition_approval,
    sign_transition_request,
)

from fdai_lifecycle_agent.hub_client import (
    MAX_CONCURRENT_WRITE_RETRIES,
    MAX_PLAN_RESPONSE_BYTES,
    FetchedArtifact,
    HttpHubClient,
    HubProtocolError,
    PlanReport,
    SignedPlan,
    validate_hub_url,
)

HUB = "http://127.0.0.1:8740"


@pytest.mark.parametrize("operation", ["state", "report"])
@pytest.mark.parametrize("initial_status", [202, 503])
def test_compressed_post_response_is_decoded_once(operation: str, initial_status: int) -> None:
    requests: list[bytes] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.content)
        status = initial_status if len(requests) == 1 else 202
        body = b'{"error":"concurrent_write"}' if status == 503 else b'{"accepted":true}'
        encoded = gzip.compress(body)
        return httpx.Response(
            status,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(encoded)),
                "retry-after": "0.05",
            },
            stream=httpx.ByteStream(encoded),
        )

    with _client(httpx.MockTransport(handler), sleeps) as client:
        if operation == "state":
            client.submit_state("installation-alpha", {"entities": []})
        else:
            client.submit_report("installation-alpha", "plan-0008", _report())

    assert len(requests) == (2 if initial_status == 503 else 1)
    assert requests[0] == requests[-1]
    assert sleeps == ([0.05] if initial_status == 503 else [])


def test_compressed_post_response_limit_uses_decoded_size() -> None:
    encoded = gzip.compress(b"x" * (MAX_PLAN_RESPONSE_BYTES + 1))
    with _client(
        httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                headers={"content-encoding": "gzip", "content-length": str(len(encoded))},
                stream=httpx.ByteStream(encoded),
            )
        )
    ) as client:
        with pytest.raises(HubProtocolError, match="size limit"):
            client.submit_state("installation-alpha", {})


def test_post_response_is_size_bounded() -> None:
    with HttpHubClient(
        HUB,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(202, content=b"x" * (MAX_PLAN_RESPONSE_BYTES + 1))
        ),
    ) as client:
        with pytest.raises(HubProtocolError, match="size limit"):
            client.submit_state("installation-alpha", {})


def test_slow_stream_stops_at_total_body_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 11.0])
    with HttpHubClient(
        HUB, transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"{}"))
    ) as client:
        monkeypatch.setattr(
            "fdai_lifecycle_agent.hub_client.time.monotonic", lambda: next(clock, 11.0)
        )
        with pytest.raises(HubProtocolError, match="deadline"):
            client.fetch_plan("installation-alpha")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_http_timeouts_are_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        HttpHubClient(HUB, timeout_seconds=timeout)


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


def test_submit_native_transition_completion_returns_durable_hub_receipt() -> None:
    digest = "sha256:" + "a" * 64
    installation_key = Ed25519PrivateKey.generate()
    hub_key = Ed25519PrivateKey.generate()
    scope = NativeScope(
        installation_id="installation-alpha",
        entity_id="fdai-workloads",
        product="example-app",
        namespace="fdai-system",
        components=("operator",),
        service_components=(),
    )
    native_approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=scope,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=datetime(2026, 10, 26, 11, 59, tzinfo=UTC),
        expires_at=datetime(2026, 10, 26, 13, 0, tzinfo=UTC),
    )
    request_values = {
        "schema_version": "fdai.lifecycle-native-transition-request.v1",
        "request_id": UUID("00000000-0000-0000-0000-000000000000"),
        "installation_id": "installation-alpha",
        "old_entity_id": "operator-hub-canary",
        "new_entity_id": "fdai-workloads",
        "old_scope_digest": digest,
        "new_scope_digest": scope.digest,
        "old_reported_state_digest": "c" * 64,
        "ownership_claim_digest": digest,
        "recovery_request_digest": digest,
        "recovered_identity_key_id": installation_key_id(
            installation_key.public_key().public_bytes_raw()
        ),
        "existing_resources_digest": existing_resources_digest([]),
        "requested_at": datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 10, 26, 12, 10, tzinfo=UTC),
    }
    request = NativeScopeTransitionRequest(
        **request_values,
        confirmation=(f"transition native scope installation-alpha {digest} {scope.digest}"),
    )
    signed_request = sign_transition_request(request, installation_key)
    hub_public = hub_key.public_key().public_bytes_raw()
    signed_approval = sign_transition_approval(
        NativeScopeTransitionApproval(
            schema_version="fdai.lifecycle-native-transition-approval.v1",
            request=signed_request,
            profile="full-authority-development",
            approved_by="owner",
            approved_at=datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
            expires_at=request.expires_at,
            recovery_audit_digest=digest,
            ownership_audit_digest=digest,
            hub_key_id=hub_key_id(hub_public),
            hub_key_epoch=1,
        ),
        hub_key,
    )
    state_document = {
        "schema_revision": 15,
        "entities": {
            "fdai-workloads": {
                "release_id": None,
                "artifact_digests": [],
                "health": "unknown",
            }
        },
        "observed_at": "2026-10-26T12:01:00.000Z",
    }
    state = NativeScopeTransitionReportedState.model_validate_json(
        json.dumps({"digest": canonical_digest(state_document), **state_document})
    )
    local_document = {
        "schema_version": "fdai.lifecycle-native-transition-receipt.v1",
        "request_digest": request.digest,
        "hub_approval_digest": signed_approval.approval.digest,
        "installation_id": "installation-alpha",
        "old_entity_id": "operator-hub-canary",
        "new_entity_id": "fdai-workloads",
        "old_scope_digest": digest,
        "new_scope_digest": scope.digest,
        "old_reported_state_digest": "c" * 64,
        "new_reported_state_digest": state.digest,
        "ownership_claim_digest": digest,
        "recovery_request_digest": digest,
        "existing_resources_digest": existing_resources_digest([]),
        "rollback_record_digest": digest,
        "completed_at": "2026-10-26T12:00:00Z",
    }
    local = NativeScopeTransitionReceipt.model_validate(
        {
            **local_document,
            "record_digest": "sha256:" + canonical_digest(local_document),
        }
    )
    completion = NativeScopeTransitionCompletion(
        schema_version="fdai.lifecycle-native-transition-completion.v1",
        approval=signed_approval,
        transition_receipt=local,
        native_approval=native_approval,
        reported_state=state,
    )
    receipt_document = {
        "schema_version": "fdai.lifecycle-native-transition-completion-receipt.v1",
        "completion_digest": completion.digest,
        "request_digest": request.digest,
        "hub_approval_digest": signed_approval.approval.digest,
        "transition_receipt_digest": local.record_digest,
        "installation_id": "installation-alpha",
        "old_entity_id": "operator-hub-canary",
        "new_entity_id": "fdai-workloads",
        "old_scope_digest": digest,
        "new_scope_digest": scope.digest,
        "old_reported_state_digest": "c" * 64,
        "new_reported_state_digest": state.digest,
        "object_scope_digest": digest,
        "authoritative_uids_digest": digest,
        "source_settings_digest": "e" * 64,
        "agent_principal": "agent-executor",
        "completed_at": "2026-10-26T12:01:00Z",
    }
    expected = NativeScopeTransitionCompletionReceipt.model_validate(
        {
            **receipt_document,
            "receipt_digest": "sha256:" + canonical_digest(receipt_document),
        }
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=expected.model_dump_json())

    with _client(httpx.MockTransport(handler)) as client:
        actual = client.submit_native_transition_completion(
            "installation-alpha",
            completion,
        )

    assert actual == expected
    assert seen == ["/v1/installations/installation-alpha/native-transition-completion"]


def test_fetch_plan_returns_none_for_no_content() -> None:
    with _client(httpx.MockTransport(lambda request: httpx.Response(204))) as client:
        assert client.fetch_plan("installation-alpha") is None


def test_fetch_artifact_reads_exact_plan_bound_signed_bytes() -> None:
    payload = b'{"schema_version":"example.v1"}'
    signature = b"s" * 64
    digest = "a" * 64
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "kind": "release",
                "digest": digest,
                "payload": base64.b64encode(payload).decode(),
                "signature": base64.b64encode(signature).decode(),
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        artifact = client.fetch_artifact("installation-alpha", "release", digest)

    assert artifact == FetchedArtifact(payload, signature)
    assert seen == [f"/v1/installations/installation-alpha/artifacts/release/{digest}"]


def test_fetch_artifact_returns_none_only_for_not_found() -> None:
    digest = "a" * 64
    with _client(httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        assert client.fetch_artifact("installation-alpha", "configuration", digest) is None

    with (
        _client(httpx.MockTransport(lambda request: httpx.Response(409))) as client,
        pytest.raises(HubProtocolError, match="returned 409"),
    ):
        client.fetch_artifact("installation-alpha", "configuration", digest)


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
