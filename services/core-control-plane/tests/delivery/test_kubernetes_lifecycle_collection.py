"""Bounded Kubernetes lifecycle collector tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from fdai.core.ontology_platform.kubernetes_lifecycle import KubernetesLifecycleCursor
from fdai.delivery.kubernetes_lifecycle_collection import KubernetesLifecycleCollector

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
CLUSTER = "scope-example/resource-group/example/providers/containerservice/example"


class _Auth:
    async def headers(self) -> dict[str, str]:
        return {"Authorization": "******", "Accept": "application/json"}


def _cursor(*, token: str | None = None, limitation: str | None = "initializing"):
    return KubernetesLifecycleCursor(
        cluster_ref=CLUSTER,
        sequence=0,
        resume_token=token,
        coverage_started_at=NOW,
        coverage_through_at=NOW,
        retention_floor_at=NOW,
        limitation=limitation,
    )


async def test_initial_collection_seeds_only_resume_token_and_current_coverage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "1"
        return httpx.Response(
            200,
            json={"metadata": {"resourceVersion": "opaque-seed"}, "items": [{}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KubernetesLifecycleCollector(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER,
            auth=_Auth(),
            http_client=client,
            now=lambda: NOW + timedelta(seconds=5),
        ).collect(_cursor())

    assert result.next_resume_token == "opaque-seed"
    assert result.coverage_started_at == NOW + timedelta(seconds=5)
    assert result.observations == ()
    assert result.limitation is None


async def test_watch_retains_typed_fields_without_message_text() -> None:
    payloads = (
        {
            "type": "MODIFIED",
            "object": {
                "metadata": {
                    "uid": "event-a",
                    "resourceVersion": "opaque-10",
                    "creationTimestamp": "2026-08-27T07:59:00Z",
                },
                "involvedObject": {
                    "uid": "pod-a",
                    "kind": "Pod",
                    "namespace": "default",
                    "ownerReferences": [{"uid": "replica-set-a", "controller": True}],
                },
                "reason": "BackOff",
                "type": "Warning",
                "message": "secret-like provider text must not persist",
                "series": {"count": 17, "lastObservedTime": "2026-08-27T08:00:10Z"},
            },
        },
        {
            "type": "BOOKMARK",
            "object": {"metadata": {"resourceVersion": "opaque-bookmark"}},
        },
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"\n".join(json.dumps(item).encode() for item in payloads),
            )
        )
    ) as client:
        result = await KubernetesLifecycleCollector(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER,
            auth=_Auth(),
            http_client=client,
            now=lambda: NOW + timedelta(seconds=20),
        ).collect(_cursor(token="opaque-seed", limitation=None))

    assert result.next_resume_token == "opaque-bookmark"
    assert result.limitation is None
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.object_uid == "pod-a"
    assert observation.owner_uid == "replica-set-a"
    assert observation.reason == "BackOff"
    assert observation.lifecycle_kind == "backoff"
    assert observation.occurrence_count == 17
    assert "secret-like" not in repr(observation)


async def test_cursor_expiry_resets_coverage_and_preserves_gap() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(410))
    ) as client:
        result = await KubernetesLifecycleCollector(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER,
            auth=_Auth(),
            http_client=client,
            now=lambda: NOW + timedelta(minutes=5),
        ).collect(_cursor(token="opaque-expired", limitation=None))

    assert result.next_resume_token is None
    assert result.coverage_started_at == NOW + timedelta(minutes=5)
    assert result.limitation == "cursor_expired"


async def test_authorization_and_outage_are_explicit() -> None:
    for response, expected in (
        (httpx.Response(403), "authorization_denied"),
        (httpx.Response(503), "source_unavailable"),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, response=response: response)
        ) as client:
            result = await KubernetesLifecycleCollector(
                api_server="https://cluster.example.com",
                cluster_ref=CLUSTER,
                auth=_Auth(),
                http_client=client,
                now=lambda: NOW + timedelta(seconds=10),
            ).collect(_cursor(token="opaque-seed", limitation=None))
        assert result.limitation == expected
        assert result.next_resume_token == "opaque-seed"


async def test_item_limit_commits_the_processed_prefix_checkpoint() -> None:
    payloads = [
        {
            "type": "ADDED",
            "object": {
                "metadata": {
                    "uid": f"event-{index}",
                    "resourceVersion": f"opaque-{index}",
                    "creationTimestamp": "2026-08-27T08:00:00Z",
                },
                "involvedObject": {"uid": f"pod-{index}", "kind": "Pod"},
                "reason": "Started",
                "type": "Normal",
            },
        }
        for index in range(257)
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"\n".join(json.dumps(item).encode() for item in payloads),
            )
        )
    ) as client:
        result = await KubernetesLifecycleCollector(
            api_server="https://cluster.example.com",
            cluster_ref=CLUSTER,
            auth=_Auth(),
            http_client=client,
            now=lambda: NOW + timedelta(seconds=20),
        ).collect(_cursor(token="opaque-seed", limitation=None))

    assert len(result.observations) == 256
    assert result.next_resume_token == "opaque-255"
    assert result.limitation == "result_limit"
