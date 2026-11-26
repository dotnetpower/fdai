from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fdai.core.metering.pricing import ModelPricing
from fdai.core.task_worker import (
    AnswerPlanningTaskWorkerExecutor,
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerRequest,
    TaskWorkerRuntime,
    TaskWorkerStatus,
    TaskWorkerUsage,
)
from fdai.core.task_worker.tools import TaskWorkerPlanningBudgetError
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.task_worker import (
    AzureTaskWorkerPlanningConfig,
    AzureTaskWorkerPlanningProvider,
)
from fdai.shared.providers.workload_identity import IdentityToken

NOW = datetime(2026, 9, 15, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.calls = 0

    async def get_token(self, audience: str) -> IdentityToken:
        self.calls += 1
        return IdentityToken("synthetic-token", NOW + timedelta(hours=1), audience)


def _config(**changes: object) -> AzureTaskWorkerPlanningConfig:
    config = AzureTaskWorkerPlanningConfig(
        target=ModelRequestTarget(
            endpoint="https://example.com", deployment="worker-example", api_version="2024-10-21"
        ),
        model_family="gpt-4.1-mini",
        pricing=ModelPricing(Decimal("0.001"), Decimal("0.002")),
    )
    return replace(config, **changes)


def _response(*, abstain: bool = False) -> dict:
    return {
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "facts": []
                            if abstain
                            else [
                                {
                                    "claim": "Selected recorded fact.",
                                    "evidence_ref": "evidence:one",
                                }
                            ],
                            "caveats": ["No selected facts."] if abstain else [],
                            "evidence_refs": [] if abstain else ["evidence:one"],
                            "confidence": 0.0 if abstain else 0.8,
                        }
                    )
                }
            }
        ],
    }


def _request(**budget: object) -> TaskWorkerRequest:
    return TaskWorkerRequest(
        worker_id="worker:budget",
        parent_trace_ref="trace:one",
        cancellation_owner="person:one",
        goal="Read selected evidence.",
        evidence_refs=("evidence:one",),
        constraints=(),
        requested_tools=frozenset(),
        budget=replace(TaskWorkerBudget(), **budget),
        created_at=NOW,
    )


def _runtime(
    provider: AzureTaskWorkerPlanningProvider, store: InMemoryTaskWorkerStore
) -> TaskWorkerRuntime:
    return TaskWorkerRuntime(
        store=store,
        executor=AnswerPlanningTaskWorkerExecutor(
            provider=provider, contributor_agent="Bragi", require_prepared=True
        ),
        tools=(),
    )


@pytest.mark.parametrize("tokens,cost", [(1, 500_000), (4096, 0)])
async def test_budget_denial_precedes_identity_and_http(tokens: int, cost: int) -> None:
    identity = _Identity()
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=identity, http_client=client
        )
        with pytest.raises(TaskWorkerPlanningBudgetError):
            await provider.contribute_bounded(
                agent="Bragi",
                prompt="Read selected evidence.",
                max_tokens=tokens,
                max_cost_microusd=cost,
            )
    assert identity.calls == 0
    assert calls == []


@pytest.mark.parametrize("abstain", [False, True])
async def test_reservation_precedes_dispatch_and_terminal_replay_is_free(abstain: bool) -> None:
    store = InMemoryTaskWorkerStore()
    identity = _Identity()
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        row = await store.get("worker:budget")
        assert row is not None and row.usage.complete is False
        assert row.usage.reserved_tokens > 0 and row.usage.reserved_cost_microusd > 0
        assert row.usage.tokens == row.usage.cost_microusd == 0
        body = json.loads(request.content)
        assert "tools" not in body and "function_call" not in body
        assert len(body["messages"]) == 1
        return httpx.Response(200, json=_response(abstain=abstain))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=identity, http_client=client
        )
        runtime = _runtime(provider, store)
        result = await runtime.run(_request(), parent_visible_tools=frozenset())
        replay = await _runtime(provider, store).run(_request(), parent_visible_tools=frozenset())
    assert result.status is (TaskWorkerStatus.ABSTAINED if abstain else TaskWorkerStatus.SUCCEEDED)
    assert result.usage == TaskWorkerUsage(tokens=80, cost_microusd=100)
    assert replay == result and len(calls) == identity.calls == 1


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": 60},
        {"prompt_tokens": True, "completion_tokens": 20, "total_tokens": 21},
        {"prompt_tokens": 60, "completion_tokens": -1, "total_tokens": 59},
        {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 81},
    ],
)
async def test_missing_or_malformed_usage_retains_unknown_reservation(usage: object) -> None:
    body = _response()
    body["usage"] = usage
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=_Identity(), http_client=client
        )
        result = await _runtime(provider, InMemoryTaskWorkerStore()).run(
            _request(), parent_visible_tools=frozenset()
        )
    assert result.status is TaskWorkerStatus.FAILED and result.summary is None
    assert not result.usage.complete and result.usage.reserved_tokens > 0
    assert result.usage.reserved_cost_microusd > 0
    assert TaskWorkerUsage.from_dict(result.usage.to_dict()) == result.usage


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"facts": [], "facts": []}',
        "[]",
        '{"facts": [], "caveats": [], "evidence_refs": [], "confidence": true}',
    ],
)
async def test_invalid_contribution_keeps_measured_usage(content: str) -> None:
    body = _response()
    body["choices"][0]["message"]["content"] = content
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=_Identity(), http_client=client
        )
        result = await _runtime(provider, InMemoryTaskWorkerStore()).run(
            _request(), parent_visible_tools=frozenset()
        )
    assert result.status is TaskWorkerStatus.FAILED
    assert result.usage == TaskWorkerUsage(tokens=80, cost_microusd=100)


@pytest.mark.parametrize("outcome", ["cancel", "timeout", "http"])
async def test_interrupted_request_and_heartbeat_never_refund_reservation(outcome: str) -> None:
    store = InMemoryTaskWorkerStore()
    entered = asyncio.Event()
    pending = asyncio.Event()
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        entered.set()
        if outcome == "http":
            raise httpx.ReadTimeout("synthetic transport timeout")
        await pending.wait()
        raise AssertionError("interrupted provider MUST NOT complete")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=_Identity(), http_client=client
        )
        runtime = _runtime(provider, store)
        request = _request(max_wall_seconds=0.1, heartbeat_seconds=0.05)
        task = await runtime.start(request, parent_visible_tools=frozenset())
        await entered.wait()
        if outcome == "cancel":
            await runtime.cancel(request.worker_id, owner=request.cancellation_owner)
        result = await task
        replay = await _runtime(provider, store).run(request, parent_visible_tools=frozenset())
    assert (
        result.status
        is {
            "cancel": TaskWorkerStatus.CANCELLED,
            "timeout": TaskWorkerStatus.TIMED_OUT,
            "http": TaskWorkerStatus.FAILED,
        }[outcome]
    )
    assert not result.usage.complete and result.usage.reserved_tokens > 0
    assert result.usage.reserved_cost_microusd > 0
    assert replay == result and calls == 1


async def test_prepared_request_tampering_is_denied_before_identity() -> None:
    identity = _Identity()
    async with httpx.AsyncClient() as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=identity, http_client=client
        )
        prepared = provider.prepare_contribution(
            agent="Bragi", prompt="Read.", max_tokens=4096, max_cost_microusd=500_000
        )
        with pytest.raises(ValueError, match="no longer matches"):
            await provider.contribute_prepared(
                replace(prepared, output_token_limit=prepared.output_token_limit + 1)
            )
    assert identity.calls == 0


def test_foreign_currency_is_not_a_usd_budget() -> None:
    with pytest.raises(ValueError, match="USD"):
        _config(pricing=ModelPricing(Decimal("1"), Decimal("2"), "KRW"))


@pytest.mark.parametrize("status", [302, 429, 503])
async def test_http_rejection_never_redirects_or_retries(status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://example.org/unused"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=_Identity(), http_client=client
        )
        result = await _runtime(provider, InMemoryTaskWorkerStore()).run(
            _request(), parent_visible_tools=frozenset()
        )
    assert len(calls) == 1
    assert result.status is TaskWorkerStatus.FAILED
    assert not result.usage.complete and result.usage.reserved_cost_microusd > 0


@pytest.mark.parametrize(
    "choices",
    [None, [], [{}, {}], [{"message": []}], [{"message": {"tool_calls": [{"id": "call"}]}}]],
)
async def test_invalid_response_shape_keeps_measured_usage(choices: object) -> None:
    body = {**_response(), "choices": choices}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=_Identity(), http_client=client
        )
        result = await _runtime(provider, InMemoryTaskWorkerStore()).run(
            _request(), parent_visible_tools=frozenset()
        )
    assert result.status is TaskWorkerStatus.FAILED and result.summary is None
    assert result.usage == TaskWorkerUsage(tokens=80, cost_microusd=100)


async def test_oversized_response_retains_unresolved_reservation() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 2048))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(max_response_bytes=1024), identity=_Identity(), http_client=client
        )
        result = await _runtime(provider, InMemoryTaskWorkerStore()).run(
            _request(), parent_visible_tools=frozenset()
        )
    assert result.status is TaskWorkerStatus.FAILED and not result.usage.complete
    assert result.usage.reserved_tokens > 0


@pytest.mark.parametrize("checkpoint", ["reservation", "measured"])
async def test_checkpoint_failure_cannot_cause_unrecorded_dispatch(checkpoint: str) -> None:
    class Store(InMemoryTaskWorkerStore):
        async def heartbeat(self, worker_id, *, usage, at):
            if (checkpoint == "reservation" and not usage.complete) or (
                checkpoint == "measured" and usage.tokens > 0
            ):
                raise RuntimeError("synthetic accounting write failure")
            return await super().heartbeat(worker_id, usage=usage, at=at)

    store, identity = Store(), _Identity()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureTaskWorkerPlanningProvider(
            config=_config(), identity=identity, http_client=client
        )
        result = await _runtime(provider, store).run(_request(), parent_visible_tools=frozenset())
    assert result.status is TaskWorkerStatus.FAILED
    assert len(calls) == identity.calls == (0 if checkpoint == "reservation" else 1)
    if checkpoint == "measured":
        assert result.usage == TaskWorkerUsage(tokens=80, cost_microusd=100)
    assert (await store.get("worker:budget")).usage == result.usage
