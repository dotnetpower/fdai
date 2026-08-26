"""Bounded Kubernetes resource event history reader tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from fdai.delivery.kubernetes_api_inventory import kubernetes_resource_id
from fdai.delivery.kubernetes_resource_event_history import (
    KubernetesResourceEventHistoryConfig,
    KubernetesResourceEventHistoryReader,
)

NOW = datetime(2026, 8, 26, 13, 5, tzinfo=UTC)
CLUSTER_REF = (
    "scope-0123456789abcdef/resource-group/example-rg/providers/"
    "microsoft.containerservice/managedclusters/example-cluster"
)


class _Auth:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-token", "Accept": "application/json"}


class _Stream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self._body


def _response(body: bytes, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, headers=headers, stream=_Stream(body))


def _json_response(payload: object) -> httpx.Response:
    return _response(json.dumps(payload, separators=(",", ":")).encode())


def _reader(
    handler: httpx.MockTransport,
    *,
    max_response_bytes: int = 262_144,
) -> KubernetesResourceEventHistoryReader:
    return KubernetesResourceEventHistoryReader(
        auth=_Auth(),
        config=KubernetesResourceEventHistoryConfig(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER_REF,
            max_response_bytes=max_response_bytes,
        ),
        client_factory=lambda: httpx.AsyncClient(transport=handler),
        now=lambda: NOW,
    )


def _event(*, uid: str = "event-uid-a", pod_uid: str = "pod-uid-a") -> dict[str, object]:
    return {
        "metadata": {
            "uid": uid,
            "namespace": "example-namespace",
            "creationTimestamp": "2026-08-26T13:00:29Z",
        },
        "involvedObject": {
            "kind": "Pod",
            "namespace": "example-namespace",
            "name": "api-example-abc",
            "uid": pod_uid,
        },
        "type": "Warning",
        "reason": "Failed",
        "message": "Error: ImagePullBackOff",
        "firstTimestamp": "2026-08-26T13:00:29Z",
        "lastTimestamp": "2026-08-26T13:03:42Z",
        "count": 11,
    }


async def test_deleted_pod_event_is_bound_to_the_selected_cluster() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/events"
        assert request.headers["accept-encoding"] == "identity"
        return _json_response(
            {
                "metadata": {"continue": ""},
                "items": [_event()],
            }
        )

    reader = _reader(httpx.MockTransport(handler))

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.limitation == "source_retention_unverified"
    assert len(result.events) == 1
    event = result.events[0]
    assert event.classification == "kubernetes_pod"
    assert event.event_family == "resource_event.kubernetes"
    assert event.event_kind == "imagepullbackoff"
    assert event.occurred_at == datetime(2026, 8, 26, 13, 3, 42, tzinfo=UTC)
    assert event.resource_id == CLUSTER_REF
    assert event.status == "warning"
    assert event.evidence_ref.startswith("kubernetes-resource-event:")


async def test_exact_pod_without_cluster_scope_stops_before_provider_io() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _json_response({"metadata": {"continue": ""}, "items": [_event()]})

    selected_id = kubernetes_resource_id(
        cluster_ref=CLUSTER_REF,
        resource_type="kubernetes.pod",
        uid="selected-pod-uid",
        namespace="example-namespace",
    )
    reader = _reader(httpx.MockTransport(handler))

    result = await reader.read_history(
        resource_ids=(selected_id,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert called is False
    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "source_scope_incomplete"


async def test_event_uid_maps_to_the_exact_current_pod() -> None:
    selected_id = kubernetes_resource_id(
        cluster_ref=CLUSTER_REF,
        resource_type="kubernetes.pod",
        uid="pod-uid-a",
        namespace="example-namespace",
    )
    reader = _reader(
        httpx.MockTransport(
            lambda request: _json_response({"metadata": {"continue": ""}, "items": [_event()]})
        )
    )

    result = await reader.read_history(
        resource_ids=tuple(sorted((CLUSTER_REF, selected_id))),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.limitation == "source_retention_unverified"
    assert len(result.events) == 1
    assert result.events[0].resource_id == selected_id


async def test_resource_outside_bound_cluster_is_incomplete_without_provider_io() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _json_response({"metadata": {"continue": ""}, "items": []})

    reader = _reader(httpx.MockTransport(handler))

    result = await reader.read_history(
        resource_ids=("resource-outside-bound-cluster",),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert called is False
    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "source_scope_incomplete"


async def test_mixed_scope_preserves_applicable_cluster_events() -> None:
    outside_id = "resource-outside-bound-cluster"
    reader = _reader(
        httpx.MockTransport(
            lambda request: _json_response({"metadata": {"continue": ""}, "items": [_event()]})
        )
    )

    result = await reader.read_history(
        resource_ids=tuple(sorted((CLUSTER_REF, outside_id))),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert len(result.events) == 1
    assert result.events[0].resource_id == CLUSTER_REF
    assert result.limitation == "source_scope_incomplete"


async def test_future_event_is_invalid_and_continuation_is_truncated() -> None:
    future_event = _event()
    future_event["lastTimestamp"] = "2026-08-26T13:06:00Z"
    responses = iter(
        (
            _json_response({"metadata": {"continue": ""}, "items": [future_event]}),
            _json_response({"metadata": {"continue": "next-page"}, "items": [_event()]}),
        )
    )
    reader = _reader(httpx.MockTransport(lambda request: next(responses)))

    future = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )
    truncated = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert future.complete is False
    assert future.limitation == "resource_event_response_invalid"
    assert truncated.complete is False
    assert truncated.limitation == "result_limit"
    assert len(truncated.events) == 1


async def test_source_failure_is_not_reported_as_verified_zero() -> None:
    reader = _reader(httpx.MockTransport(lambda request: httpx.Response(403)))

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "source_unavailable"


async def test_list_without_pagination_metadata_is_invalid() -> None:
    reader = _reader(httpx.MockTransport(lambda request: _json_response({"items": [_event()]})))

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "resource_event_response_invalid"


async def test_single_oversized_response_chunk_is_rejected() -> None:
    reader = _reader(
        httpx.MockTransport(lambda request: _response(b"x" * 1025)),
        max_response_bytes=1024,
    )

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "resource_event_response_invalid"


async def test_encoded_response_is_rejected_before_decompression() -> None:
    reader = _reader(
        httpx.MockTransport(
            lambda request: _response(
                b"not-decompressed",
                headers={"Content-Encoding": "gzip"},
            )
        )
    )

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "resource_event_response_invalid"


async def test_non_string_continuation_is_invalid() -> None:
    reader = _reader(
        httpx.MockTransport(
            lambda request: _json_response({"metadata": {"continue": 1}, "items": []})
        )
    )

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.events == ()
    assert result.limitation == "resource_event_response_invalid"


async def test_provider_item_overflow_processes_only_the_result_bound() -> None:
    items = [_event(uid=f"event-{index}") for index in range(258)]
    reader = _reader(
        httpx.MockTransport(
            lambda request: _json_response({"metadata": {"continue": ""}, "items": items})
        )
    )

    result = await reader.read_history(
        resource_ids=(CLUSTER_REF,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert len(result.events) == 256
    assert result.limitation == "result_limit"
