"""Offline checks of aggregate limits through real sync-to-async model adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.conversation.adaptive_call_scope import bind_adaptive_model_budget
from fdai.core.conversation.adaptive_models import AdaptivePolicy
from fdai.core.conversation.adaptive_service import _Budget
from fdai.delivery.azure.llm.semantic_judgment import (
    AzureOpenAISemanticJudgmentModel,
    AzureOpenAISemanticJudgmentModelConfig,
)
from fdai.delivery.azure.llm.semantic_planning import AzureOpenAISemanticPlanningModel
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

from tests.delivery.azure.llm.test_semantic_planning import _config, _frame_payload, _target


def _invoker(kind: str, client: httpx.AsyncClient) -> Callable[[], Awaitable[object]]:
    identity = AsyncMock(spec=WorkloadIdentity)
    identity.get_token.return_value = IdentityToken(
        token="synthetic-test-token",
        expires_at=datetime(2026, 9, 6, tzinfo=UTC),
        audience="https://example.com",
    )
    targets = (_target("primary"), _target("secondary"))
    if kind == "planner":
        planner = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=client,
            config=_config(*targets),
            owner_loop=asyncio.get_running_loop(),
        )
        call = partial(
            planner.propose_frame,
            utterance="Read a scoped example.",
            context=(),
            descriptors=(),
            metric_concepts=(),
            principal_role="reader",
            purpose="operations-review",
        )
    else:
        judgment = AzureOpenAISemanticJudgmentModel(
            identity=identity,
            http_client=client,
            config=AzureOpenAISemanticJudgmentModelConfig(
                candidates=targets,
                system_prompt="Propose meaning without authority.",
                timeout_seconds=2,
            ),
            owner_loop=asyncio.get_running_loop(),
        )
        call = partial(
            judgment.judge,
            utterance="Read a scoped example.",
            context=(),
            capabilities=(),
            locale="en",
            direct_response_profile={},
            direct_response_profile_digest="sha256:" + "a" * 64,
            profile_id="example",
            profile_version="1.0.0",
            schema_repair=(),
        )

    async def invoke() -> object:
        return await asyncio.to_thread(call)

    return invoke


def _response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(_frame_payload())}}],
            "usage": {"total_tokens": 500},
        },
    )


@pytest.mark.parametrize("kind", ["planner", "judgment"])
async def test_nested_provider_usage_and_calls_share_the_turn_budget(kind: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response()

    budget = _Budget(AdaptivePolicy())
    budget.reserve(100, 256, 0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        invoke = _invoker(kind, client)
        async with bind_adaptive_model_budget(budget, reserved_calls=2):
            assert await invoke() is not None
            assert await invoke() is not None
            assert await invoke() is None
        assert len(requests) == 2
        assert budget.calls == 3
        assert budget.tokens == 1356
        assert len(budget.observations) == 2
        assert budget.reserve(100, 256, 0) == 356
        assert budget.reserve(100, 256, 0) == 356


@pytest.mark.parametrize("kind", ["planner", "judgment"])
@pytest.mark.parametrize("status", [429, 503])
async def test_provider_failure_ends_the_scope_without_candidate_failover(
    kind: str,
    status: int,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    budget = _Budget(AdaptivePolicy())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        invoke = _invoker(kind, client)
        async with bind_adaptive_model_budget(budget):
            assert await invoke() is None
            assert await invoke() is None
    assert len(requests) == 1
    assert budget.calls == 1
    assert budget.tokens > 0


@pytest.mark.parametrize("kind", ["planner", "judgment"])
async def test_closing_the_read_scope_cancels_active_provider_work(kind: str) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()
        raise AssertionError("cancelled provider must not return")

    budget = _Budget(AdaptivePolicy())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        invoke = _invoker(kind, client)
        async with asyncio.TaskGroup() as tasks:
            async with bind_adaptive_model_budget(budget):
                pending = tasks.create_task(invoke())
                await asyncio.wait_for(started.wait(), timeout=1)
            assert stopped.is_set()
            assert await asyncio.wait_for(pending, timeout=1) is None
    assert budget.calls == 1
    assert budget.tokens > 0


@pytest.mark.parametrize("kind", ["planner", "judgment"])
async def test_exhausted_tokens_prevent_network_and_do_not_leak_into_the_next_turn(
    kind: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response()

    budget = _Budget(AdaptivePolicy(max_tokens=4096))
    budget.reserve(3000, 1000, 0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        invoke = _invoker(kind, client)
        async with bind_adaptive_model_budget(budget):
            assert await invoke() is None
        assert requests == []
        assert await invoke() is not None
    assert len(requests) == 1
    assert budget.calls == 1
    assert budget.tokens == 4000
