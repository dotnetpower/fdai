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


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk


def _chunked_response(*chunks: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, stream=_ChunkedStream(chunks))


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


async def test_watch_event_count_cap_is_an_explicit_truncation_gap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ndjson_response(
            *(
                {
                    "type": "ADDED",
                    "object": _event_object(
                        event_uid=f"event-uid-{index}",
                        resource_version=str(3000 + index),
                    ),
                }
                for index in range(256)
            )
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    assert len(poll.observations) == 256


async def test_malformed_envelope_before_watch_cap_prevents_safe_progress() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            b"{malformed}\n"
            + b"".join(
                json.dumps(
                    {
                        "type": "ADDED",
                        "object": _event_object(
                            event_uid=f"event-uid-{index}",
                            resource_version=str(4000 + index),
                        ),
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n"
                for index in range(255)
            )
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "lifecycle_response_invalid"
    assert poll.cursor_safe is False


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
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        # Every page still advertises a `continue` token, so the list never drains
        # within the bounded page budget.
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
    # An incomplete drain MUST NOT advance the cursor to the snapshot's
    # `resourceVersion`: doing so would silently skip every unconsumed
    # continuation page forever.
    assert poll.next_cursor is None
    # The internal page budget bounds provider I/O even under an infinite
    # continuation loop.
    assert call_count == 8


async def test_list_pagination_drains_within_budget_and_advances_the_cursor() -> None:
    pages_seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages_seen.append(request.url.params.get("continue"))
        if request.url.params.get("continue") is None:
            return _json_response(
                {
                    "metadata": {"resourceVersion": "2000", "continue": "page-2-token"},
                    "items": [_event_object(event_uid="event-uid-a", object_uid="pod-uid-a")],
                }
            )
        return _json_response(
            {
                "metadata": {"resourceVersion": "2001"},
                "items": [
                    _event_object(
                        event_uid="event-uid-b",
                        object_uid="pod-uid-b",
                        resource_version="1002",
                    )
                ],
            }
        )

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is True
    assert poll.limitation is None
    # The cursor only ever advances to the *final* page's snapshot resourceVersion.
    assert poll.next_cursor == "2001"
    assert len(poll.observations) == 2
    assert pages_seen == [None, "page-2-token"]


async def test_list_drains_more_than_one_output_page_before_advancing_cursor() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _json_response(
                {
                    "metadata": {"resourceVersion": "3000", "continue": "page-2"},
                    "items": [
                        _event_object(
                            event_uid=f"event-a-{index}",
                            resource_version=str(5000 + index),
                        )
                        for index in range(256)
                    ],
                }
            )
        return _json_response(
            {
                "metadata": {"resourceVersion": "3001"},
                "items": [_event_object(event_uid="event-b", resource_version="6000")],
            }
        )

    poll = await _source(httpx.MockTransport(handler)).poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is True
    assert poll.next_cursor == "3001"
    assert len(poll.observations) == 257


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


async def test_list_401_reports_authorization_failed_not_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"", status_code=401)

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is False
    assert poll.limitation == "authorization_failed"
    assert poll.observations == ()


async def test_list_403_reports_authorization_failed_not_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"", status_code=403)

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor=None)

    assert poll.complete is False
    assert poll.limitation == "authorization_failed"


async def test_watch_401_reports_authorization_failed_and_preserves_the_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"", status_code=401)

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "authorization_failed"
    # A 401/403 is a distinct classification from a generic outage, but it MUST
    # still preserve the durable cursor exactly like a `source_unavailable` gap.
    assert poll.next_cursor == "2000"


async def test_watch_403_reports_authorization_failed_and_preserves_the_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(b"", status_code=403)

    source = _source(httpx.MockTransport(handler))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "authorization_failed"
    assert poll.next_cursor == "2000"


async def test_watch_byte_bound_truncation_reports_result_limit() -> None:
    first_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2001", reason="Started")},
        separators=(",", ":"),
    ).encode()
    # A second, oversized chunk pushes the running total past the configured
    # response byte bound partway through the stream.
    overflow_chunk = b"x" * 2048
    source = _source(
        httpx.MockTransport(lambda request: _chunked_response(first_line + b"\n", overflow_chunk)),
        max_response_bytes=1_024,
    )

    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    # The fully-received first line MUST still be honored...
    assert len(poll.observations) == 1
    # ...and the cursor MUST NOT advance past it into the discarded remainder.
    assert poll.next_cursor == "2001"


async def test_watch_oversized_line_reports_result_limit_without_skipping_ahead() -> None:
    good_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2001", reason="Started")},
        separators=(",", ":"),
    ).encode()
    oversized_line = b"{" + b"x" * 70_000
    trailing_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2099", reason="Failed")},
        separators=(",", ":"),
    ).encode()
    body = good_line + b"\n" + oversized_line + b"\n" + trailing_line + b"\n"

    source = _source(httpx.MockTransport(lambda request: _response(body)))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    assert len(poll.observations) == 1
    # The cursor MUST stop at the last-good envelope, never at the trailing one
    # that arrived only after the discarded oversized line.
    assert poll.next_cursor == "2001"


async def test_watch_undecodable_line_reports_result_limit_without_skipping_ahead() -> None:
    good_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2001", reason="Started")},
        separators=(",", ":"),
    ).encode()
    bad_line = b"\xff\xfe not valid utf-8"
    trailing_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2099", reason="Failed")},
        separators=(",", ":"),
    ).encode()
    body = good_line + b"\n" + bad_line + b"\n" + trailing_line + b"\n"

    source = _source(httpx.MockTransport(lambda request: _response(body)))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    assert len(poll.observations) == 1
    assert poll.next_cursor == "2001"


async def test_watch_oversized_trailing_buffer_reports_result_limit() -> None:
    good_line = json.dumps(
        {"type": "ADDED", "object": _event_object(resource_version="2001", reason="Started")},
        separators=(",", ":"),
    ).encode()
    # No trailing newline: an oversized unterminated final buffer MUST be flagged
    # exactly like an oversized complete line, never silently dropped.
    oversized_trailing_buffer = b"{" + b"x" * 70_000
    body = good_line + b"\n" + oversized_trailing_buffer

    source = _source(httpx.MockTransport(lambda request: _response(body)))
    poll = await source.poll(cluster_ref=CLUSTER_REF, cursor="2000")

    assert poll.complete is False
    assert poll.limitation == "result_limit"
    assert len(poll.observations) == 1
    assert poll.next_cursor == "2001"
