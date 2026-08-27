"""Bounded resumable Kubernetes lifecycle source (list-then-watch) tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from fdai.delivery.kubernetes_lifecycle_source import (
    KubernetesLifecycleSourceConfig,
    KubernetesLifecycleWatchSource,
)

NOW = datetime(2026, 8, 27, 13, 5, tzinfo=UTC)
CLUSTER_REF = "cluster-a"


class _Auth:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "******", "Accept": "application/json"}


class _FailingAuth:
    async def headers(self) -> dict[str, str]:
        raise RuntimeError("token unavailable")


class _Stream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self._body


def _response(body: bytes, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, stream=_Stream(body))


def _json_response(payload: object, *, status_code: int = 200) -> httpx.Response:
    return _response(json.dumps(payload, separators=(",", ":")).encode(), status_code=status_code)


def _ndjson_response(*envelopes: object) -> httpx.Response:
    lines = "\n".join(json.dumps(envelope, separators=(",", ":")) for envelope in envelopes)
    return _response((lines + "\n").encode())


def _source(
    handler: httpx.MockTransport,
    *,
    auth: object | None = None,
    max_response_bytes: int = 262_144,
) -> KubernetesLifecycleWatchSource:
    return KubernetesLifecycleWatchSource(
        auth=auth or _Auth(),
        config=KubernetesLifecycleSourceConfig(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER_REF,
            max_response_bytes=max_response_bytes,
        ),
        client_factory=lambda: httpx.AsyncClient(transport=handler),
        now=lambda: NOW,
    )


def _event_object(
    *,
    event_uid: str = "event-uid-a",
    object_uid: str = "pod-uid-a",
    reason: str = "Killing",
    resource_version: str = "1001",
    event_type: str = "Normal",
    owner_uid: str | None = None,
) -> dict[str, object]:
    related: dict[str, object] = {}
    if owner_uid is not None:
        related = {"related": {"uid": owner_uid}}
    return {
        "metadata": {
            "uid": event_uid,
            "resourceVersion": resource_version,
            "creationTimestamp": "2026-08-27T13:00:00Z",
        },
        "involvedObject": {
            "kind": "Pod",
            "namespace": "example-namespace",
            "name": "api-example-abc",
            "uid": object_uid,
        },
        "type": event_type,
        "reason": reason,
        "message": "human-readable prose that MUST NOT affect identity",
        "firstTimestamp": "2026-08-27T13:00:00Z",
        "lastTimestamp": "2026-08-27T13:00:29Z",
        **related,
    }


async def test_first_poll_with_no_cursor_lists_and_establishes_a_baseline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/events"
        assert "resourceVersion" not in request.url.params
        return _json_response(
            {
                "metadata": {"resourceVersion": "2000"},
                "items": [_event_object()],
            }
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is True
    assert poll.limitation is None
    assert poll.next_cursor == "2000"
    assert len(poll.observations) == 1
    observation = poll.observations[0]
    assert observation.category == "killing"
    assert observation.reason == "Killing"
    assert observation.object_uid == "pod-uid-a"
    assert observation.owner_uid is None
    assert observation.source_revision == "1001"


async def test_list_captures_owner_uid_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "metadata": {"resourceVersion": "2000"},
                "items": [_event_object(owner_uid="replicaset-uid-a")],
            }
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.observations[0].owner_uid == "replicaset-uid-a"


async def test_subsequent_poll_with_a_cursor_watches_and_resumes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["watch"] == "true"
        assert request.url.params["resourceVersion"] == "2000"
        return _ndjson_response(
            {"type": "ADDED", "object": _event_object(resource_version="2001", reason="Started")},
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is True
    assert poll.next_cursor == "2001"
    assert len(poll.observations) == 1
    assert poll.observations[0].category == "started"


async def test_watch_bookmark_advances_cursor_without_an_observation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ndjson_response(
            {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "2050"}}},
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is True
    assert poll.observations == ()
    assert poll.next_cursor == "2050"


async def test_watch_gone_error_surfaces_an_explicit_cursor_expiry_gap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ndjson_response({"type": "ERROR", "object": {"code": 410}})

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "cursor_expired"
    assert poll.next_cursor is None
    assert poll.observations == ()


async def test_watch_hard_410_status_surfaces_cursor_expiry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"", status_code=410)

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "cursor_expired"
    assert poll.next_cursor is None


async def test_network_outage_is_an_explicit_source_unavailable_gap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is False
    assert poll.limitation == "source_unavailable"
    assert poll.observations == ()
    assert poll.next_cursor is None


async def test_outage_while_resuming_preserves_the_existing_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "source_unavailable"
    assert poll.observations == ()
    # A transient outage MUST NOT discard an already-durable checkpoint; only an
    # explicit cursor-expiry gap resets the cursor to `None`.
    assert poll.next_cursor == "2000"


async def test_authorization_failure_while_resuming_preserves_the_existing_cursor() -> None:
    source = _source(httpx.MockTransport(lambda request: _json_response({})), auth=_FailingAuth())
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "authorization_failed"
    assert poll.next_cursor == "2000"


async def test_authorization_failure_is_an_explicit_gap_before_any_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _json_response({"metadata": {"resourceVersion": "2000"}, "items": []})

    source = _source(httpx.MockTransport(handler), auth=_FailingAuth())
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert called is False
    assert poll.complete is False
    assert poll.limitation == "authorization_failed"


async def test_list_truncation_reports_result_limit_and_stays_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "metadata": {"resourceVersion": "2000", "continue": "next-page-token"},
                "items": [_event_object()],
            }
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    assert poll.next_cursor == "2000"


async def test_malformed_response_never_raises_and_reports_response_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"not-json")

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is False
    assert poll.limitation == "lifecycle_response_invalid"


async def test_poll_rejects_a_foreign_cluster_ref_before_any_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _json_response({"metadata": {"resourceVersion": "2000"}, "items": []})

    source = _source(httpx.MockTransport(handler))
    try:
        await source.poll(cluster_ref="cluster-other", cursor=None)
    except ValueError as exc:
        assert "foreign cluster_ref" in str(exc)
    else:
        raise AssertionError("expected a ValueError for a foreign cluster_ref")
    assert called is False


async def test_deletion_reasons_normalize_without_reading_message_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "metadata": {"resourceVersion": "2000"},
                "items": [_event_object(reason="SuccessfulDelete")],
            }
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.observations[0].category == "deletion"
