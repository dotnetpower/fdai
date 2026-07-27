"""Tests for the SREGym conductor translation boundary."""

from __future__ import annotations

import json

import httpx
import pytest
from fdai_bench_sregym import SregymAdapter, SregymAdapterConfig

from fdai.benchmarking import BenchmarkStatus, BenchmarkSubmission
from fdai.benchmarking.adapter import BenchmarkAdapterError


def _adapter(handler) -> tuple[SregymAdapter, httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        SregymAdapter(
            config=SregymAdapterConfig(
                conductor_url="http://127.0.0.1:8000",
                artifact_id="attempt-1",
                poll_interval_seconds=0.001,
                stage_timeout_seconds=0.01,
            ),
            http_client=client,
        ),
        client,
    )


async def test_translates_diagnosis_and_submits_result() -> None:
    submitted: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        if request.url.path == "/submit":
            submitted.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "200"})
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    assert task.stage == "diagnosis"
    assert task.target_ref == "kubernetes.namespace/example"

    await adapter.submit(
        BenchmarkSubmission(
            run_id=task.run_id,
            task_id=task.task_id,
            stage=task.stage,
            status=BenchmarkStatus.COMPLETED,
            summary="The backend dependency is unavailable.",
        )
    )

    assert submitted == [{"solution": "The backend dependency is unavailable."}]
    await client.aclose()


async def test_submit_rejects_unissued_task() -> None:
    submit_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_calls
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/submit":
            submit_calls += 1
            return httpx.Response(200, json={"status": "200"})
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()

    with pytest.raises(BenchmarkAdapterError, match="no SREGym task is awaiting submission"):
        await adapter.submit(
            BenchmarkSubmission(
                run_id="attempt-1",
                task_id="attempt-1",
                stage="diagnosis",
                status=BenchmarkStatus.COMPLETED,
                summary="Unissued result.",
            )
        )

    assert submit_calls == 0
    await client.aclose()


async def test_submit_rejects_mismatched_issued_task() -> None:
    submit_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_calls
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        if request.url.path == "/submit":
            submit_calls += 1
            return httpx.Response(200, json={"status": "200"})
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None

    with pytest.raises(BenchmarkAdapterError, match="does not match the issued SREGym task"):
        await adapter.submit(
            BenchmarkSubmission(
                run_id=task.run_id,
                task_id=task.task_id,
                stage="mitigation",
                status=BenchmarkStatus.COMPLETED,
                summary="Wrong-stage result.",
            )
        )

    assert submit_calls == 0
    await client.aclose()


async def test_next_task_rejects_outstanding_task() -> None:
    status_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_calls
        if request.url.path == "/status":
            status_calls += 1
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None

    with pytest.raises(BenchmarkAdapterError, match="task is already awaiting submission"):
        await adapter.next_task()

    assert status_calls == 2
    await client.aclose()


async def test_submit_normalizes_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        if request.url.path == "/submit":
            raise httpx.ReadTimeout("submit timed out", request=request)
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    submission = BenchmarkSubmission(
        run_id=task.run_id,
        task_id=task.task_id,
        stage=task.stage,
        status=BenchmarkStatus.COMPLETED,
        summary="Evidence-backed result.",
    )

    with pytest.raises(BenchmarkAdapterError, match="submit request failed") as error:
        await adapter.submit(submission)

    assert isinstance(error.value.__cause__, httpx.ReadTimeout)
    await client.aclose()


async def test_rejects_response_over_byte_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "x" * 100,
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        raise AssertionError(request.url.path)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SregymAdapter(
        config=SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
            max_response_bytes=64,
        ),
        http_client=client,
    )
    await adapter.start()

    with pytest.raises(BenchmarkAdapterError, match="over the 64-byte cap"):
        await adapter.next_task()

    await client.aclose()


async def test_rejects_submit_response_over_byte_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "example-shop",
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        if request.url.path == "/submit":
            return httpx.Response(200, content=b"x" * 256)
        raise AssertionError(request.url.path)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SregymAdapter(
        config=SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
            max_response_bytes=128,
        ),
        http_client=client,
    )
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None

    with pytest.raises(BenchmarkAdapterError, match="submit.*over the 128-byte cap"):
        await adapter.submit(
            BenchmarkSubmission(
                run_id=task.run_id,
                task_id=task.task_id,
                stage=task.stage,
                status=BenchmarkStatus.COMPLETED,
                summary="Evidence-backed result.",
            )
        )

    await client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8000",
        "https://user@example.com",
        "https://example.com?token=value",
    ],
)
def test_rejects_unsafe_conductor_urls(url: str) -> None:
    with pytest.raises(ValueError):
        SregymAdapterConfig(conductor_url=url, artifact_id="attempt-1")


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:abc",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
    ),
)
def test_rejects_invalid_conductor_port(url: str) -> None:
    with pytest.raises(ValueError, match="conductor_url port MUST be between 1 and 65535"):
        SregymAdapterConfig(conductor_url=url, artifact_id="attempt-1")


@pytest.mark.parametrize("timeout", (float("nan"), float("inf"), float("-inf")))
def test_rejects_non_finite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeouts MUST be finite and positive"):
        SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
            request_timeout_seconds=timeout,
        )


def test_accepts_upstream_container_host_alias() -> None:
    config = SregymAdapterConfig(
        conductor_url="http://host.docker.internal:8000",
        artifact_id="attempt-1",
    )

    assert config.conductor_url == "http://host.docker.internal:8000"


def test_rejects_non_positive_response_limit() -> None:
    with pytest.raises(ValueError, match="max_response_bytes MUST be >= 1"):
        SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
            max_response_bytes=0,
        )


async def test_fails_closed_on_unknown_stage() -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json={"stage": "unknown-stage"}))

    with pytest.raises(RuntimeError, match="unsupported SREGym stage"):
        await adapter.start()

    await client.aclose()
