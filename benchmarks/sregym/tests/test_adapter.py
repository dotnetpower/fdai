"""Tests for the SREGym conductor translation boundary."""

from __future__ import annotations

import json

import httpx
import pytest
from fdai_evaluation_sdk import (
    AuthorityCeiling,
    DecisionReceipt,
    EvaluationResult,
    EvaluationStatus,
    QualityGateStatus,
)

from fdai_bench_sregym import SregymAdapter, SregymAdapterConfig, SregymAdapterError


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


def _result(
    *,
    session_id: str = "attempt-1",
    task_id: str = "diagnosis-0000000000000000",
    phase: str = "diagnosis",
    summary: str = "Evidence-backed result.",
) -> EvaluationResult:
    return EvaluationResult(
        session_id=session_id,
        task_id=task_id,
        phase=phase,
        status=EvaluationStatus.COMPLETED,
        summary=summary,
        terminal_audit_ref="audit/example",
        decision_receipt=DecisionReceipt(
            selected_tier="t0",
            control_loop_outcome="executed",
            decision="complete",
            autonomy_mode=AuthorityCeiling.SHADOW,
            verifier_passed=True,
            quality_gate_status=QualityGateStatus.NOT_REQUIRED,
            authority_ceiling=AuthorityCeiling.SHADOW,
        ),
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
    request = await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    assert request.session_id == "attempt-1"
    assert {item.capability_id for item in request.requested_capabilities} >= {
        "observe.kubernetes.capacity",
        "observe.kubernetes.inventory",
        "observe.kubernetes.nodes",
        "observe.metrics.query",
    }
    assert task.phase == "diagnosis"
    assert task.target.kind == "kubernetes.namespace"
    assert task.target.value == "example"

    await adapter.submit(
        _result(
            session_id=task.session_id,
            task_id=task.task_id,
            phase=task.phase,
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

    with pytest.raises(SregymAdapterError, match="no SREGym task is awaiting submission"):
        await adapter.submit(_result(summary="Unissued result."))

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

    with pytest.raises(SregymAdapterError, match="does not match the issued SREGym task"):
        await adapter.submit(
            _result(
                session_id=task.session_id,
                task_id=task.task_id,
                phase="mitigation",
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

    with pytest.raises(SregymAdapterError, match="task is already awaiting submission"):
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
    submission = _result(
        session_id=task.session_id,
        task_id=task.task_id,
        phase=task.phase,
        summary="Evidence-backed result.",
    )

    with pytest.raises(SregymAdapterError, match="submit request failed") as error:
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

    with pytest.raises(SregymAdapterError, match="over the 64-byte cap"):
        await adapter.next_task()

    await client.aclose()


async def test_normalizes_invalid_application_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": "diagnosis"})
        if request.url.path == "/get_app":
            return httpx.Response(
                200,
                json={
                    "app_name": "x" * 3_000,
                    "namespace": "example",
                    "descriptions": "Requests return errors.",
                },
            )
        raise AssertionError(request.url.path)

    adapter, client = _adapter(handler)
    await adapter.start()

    with pytest.raises(SregymAdapterError, match="application payload is invalid") as error:
        await adapter.next_task()

    assert isinstance(error.value.__cause__, SregymAdapterError)
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

    with pytest.raises(SregymAdapterError, match="submit.*over the 128-byte cap"):
        await adapter.submit(
            _result(
                session_id=task.session_id,
                task_id=task.task_id,
                phase=task.phase,
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


@pytest.mark.parametrize("artifact_id", ("a" * 257, "attempt\u202e1"))
def test_rejects_invalid_artifact_identity(artifact_id: str) -> None:
    with pytest.raises(ValueError, match="artifact_id MUST be a non-empty bounded identifier"):
        SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id=artifact_id,
        )


async def test_fails_closed_on_unknown_stage() -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json={"stage": "unknown-stage"}))

    with pytest.raises(RuntimeError, match="unsupported SREGym stage"):
        await adapter.start()

    await client.aclose()


async def test_fails_closed_when_stage_becomes_unknown_after_start() -> None:
    status_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_calls
        if request.url.path != "/status":
            raise AssertionError(request.url.path)
        status_calls += 1
        stage = "diagnosis" if status_calls == 1 else "unknown-stage"
        return httpx.Response(200, json={"stage": stage})

    adapter, client = _adapter(handler)
    await adapter.start()

    with pytest.raises(SregymAdapterError, match="unsupported SREGym stage 'unknown-stage'"):
        await adapter.next_task()

    assert status_calls == 2
    await client.aclose()


async def test_rejects_task_before_start_and_returns_terminal_none() -> None:
    adapter, client = _adapter(lambda _: httpx.Response(200, json={"stage": "done"}))

    with pytest.raises(SregymAdapterError, match="MUST be started"):
        await adapter.next_task()
    await adapter.start()
    assert await adapter.next_task() is None
    await client.aclose()


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (httpx.Response(200, content=b"not-json"), "is not JSON"),
        (httpx.Response(200, json=["not-an-object"]), "is not an object"),
        (httpx.Response(503), "returned HTTP 503"),
    ),
)
async def test_normalizes_malformed_and_failed_status_response(
    response: httpx.Response,
    message: str,
) -> None:
    adapter, client = _adapter(lambda _: response)

    with pytest.raises(SregymAdapterError, match=message):
        await adapter.start()
    await client.aclose()


async def test_normalizes_get_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("status timed out", request=request)

    adapter, client = _adapter(handler)
    with pytest.raises(SregymAdapterError, match="request '/status' failed") as error:
        await adapter.start()
    assert isinstance(error.value.__cause__, httpx.ReadTimeout)
    await client.aclose()


@pytest.mark.parametrize(
    ("stage", "expected"),
    (
        ("mitigation", "governed recovery"),
        ("resolution", "resolution evidence"),
    ),
)
async def test_maps_non_diagnosis_objectives(stage: str, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"stage": stage})
        return httpx.Response(
            200,
            json={
                "app_name": "example-shop",
                "namespace": "example",
                "descriptions": "Requests return errors.",
            },
        )

    adapter, client = _adapter(handler)
    await adapter.start()
    task = await adapter.next_task()
    assert task is not None
    assert expected in task.objective
    await client.aclose()


async def test_owned_http_client_closes() -> None:
    adapter = SregymAdapter(
        config=SregymAdapterConfig(
            conductor_url="http://127.0.0.1:8000",
            artifact_id="attempt-1",
        )
    )
    assert adapter._http.is_closed is False  # noqa: SLF001
    await adapter.close()
    assert adapter._http.is_closed is True  # noqa: SLF001
