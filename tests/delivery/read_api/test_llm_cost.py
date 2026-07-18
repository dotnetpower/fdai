"""Tests for the LLM cost read panel (unit + build_app integration)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.llm_cost import LlmCostPanel

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"


def _inv(
    *,
    corr: str,
    when: datetime,
    prompt: int,
    completion: int,
    cost: str | None,
    model: str = "gpt-4o",
    scope: InvocationScope = InvocationScope.CONTROL_PLANE,
) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=when,
        correlation_id=corr,
        capability_id="t2.reasoner.primary",
        model_key=model,
        tier="T2",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        usage_scope=scope,
        cost=None if cost is None else Decimal(cost),
    )


async def _seeded_sink() -> InMemoryMeteringSink:
    sink = InMemoryMeteringSink()
    await sink.record(
        _inv(
            corr="evt-a",
            when=datetime(2026, 7, 9, 10, tzinfo=UTC),
            prompt=1000,
            completion=200,
            cost="0.30",
        )
    )
    await sink.record(
        _inv(
            corr="evt-a",
            when=datetime(2026, 7, 9, 11, tzinfo=UTC),
            prompt=500,
            completion=100,
            cost="0.20",
        )
    )
    await sink.record(
        _inv(
            corr="evt-b",
            when=datetime(2026, 7, 10, 9, tzinfo=UTC),
            prompt=800,
            completion=50,
            cost=None,
            model="gpt-4.1-mini",
            scope=InvocationScope.OPERATOR_CHAT,
        )
    )
    return sink


async def test_render_all_groupings() -> None:
    panel = LlmCostPanel(await _seeded_sink())
    payload = await panel.render(params={})
    assert payload["source"] == "metering"
    assert payload["latest_occurred_at"] == "2026-07-10T09:00:00+00:00"
    assert payload["invocations"] == 3
    assert payload["total"]["total_tokens"] == 2650
    assert payload["chat"]["total_tokens"] == 850
    assert payload["chat_by_model"] == [
        {
            "key": "gpt-4.1-mini",
            "invocations": 1,
            "prompt_tokens": 800,
            "completion_tokens": 50,
            "total_tokens": 850,
        }
    ]
    assert [row["key"] for row in payload["by_model"]] == ["gpt-4.1-mini", "gpt-4o"]
    assert payload["records"][0]["model_key"] == "gpt-4.1-mini"
    assert payload["records"][0]["usage_scope"] == "operator_chat"
    assert "cost" not in payload["total"]
    assert "currency" not in payload
    assert [row["key"] for row in payload["by_conversation"]] == ["evt-a", "evt-b"]
    assert [row["key"] for row in payload["by_day"]] == ["2026-07-09", "2026-07-10"]
    assert [row["key"] for row in payload["by_month"]] == ["2026-07"]
    # H8: shadow-vs-enforce split is always present.
    assert "by_mode" in payload
    assert payload["by_conversation_truncated"] is False
    assert payload["conversation_count"] == 2


async def test_by_conversation_capped_and_flagged() -> None:
    # H6: a large conversation set is capped (costliest first) and flagged.
    sink = InMemoryMeteringSink()
    for i in range(5):
        await sink.record(
            _inv(
                corr=f"evt-{i}",
                when=datetime(2026, 7, 10, 9, tzinfo=UTC),
                prompt=100,
                completion=10,
                cost=f"0.0{i}",
            )
        )
    panel = LlmCostPanel(sink, max_conversations=2)
    payload = await panel.render(params={})
    assert payload["by_conversation_truncated"] is True
    assert payload["conversation_count"] == 5
    assert len(payload["by_conversation"]) == 2
    assert [r["key"] for r in payload["by_conversation"]] == ["evt-0", "evt-1"]


async def test_render_group_filter() -> None:
    panel = LlmCostPanel(await _seeded_sink())
    payload = await panel.render(params={"group": "month"})
    assert "by_month" in payload
    assert "by_day" not in payload
    assert "by_conversation" not in payload


async def test_render_unknown_group_falls_back_to_all() -> None:
    panel = LlmCostPanel(await _seeded_sink())
    payload = await panel.render(params={"group": "bogus"})
    assert "by_day" in payload and "by_month" in payload and "by_conversation" in payload


def test_panel_rejects_bad_path() -> None:
    with pytest.raises(ValueError, match="MUST start with"):
        LlmCostPanel(InMemoryMeteringSink(), path="kpi/llm-cost")


def test_panel_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source"):
        LlmCostPanel(InMemoryMeteringSink(), source="")


def test_panel_rejects_bad_max_conversations() -> None:
    with pytest.raises(ValueError, match="max_conversations"):
        LlmCostPanel(InMemoryMeteringSink(), max_conversations=0)


def test_panel_metadata() -> None:
    panel = LlmCostPanel(InMemoryMeteringSink())
    assert panel.path == "/kpi/llm-cost"
    assert panel.name == "llm-cost"


async def test_empty_metering_has_no_latest_invocation() -> None:
    payload = await LlmCostPanel(InMemoryMeteringSink()).render(params={})
    assert payload["latest_occurred_at"] is None


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(_DEV_MODE_ENV, "1")
    yield


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


def test_build_app_serves_llm_cost_route(dev_env: None) -> None:
    del dev_env
    sink = asyncio.run(_seeded_sink())
    resolver = RoleResolver(group_mapping=_mapping())
    authenticator = build_authenticator(verifier=UnsafeClaimsExtractor(), resolver=resolver)
    config = ReadApiConfig(dev_mode=True, extra_panels=(LlmCostPanel(sink),))
    app = build_app(
        authenticator=authenticator,
        read_model=InMemoryConsoleReadModel(),
        config=config,
    )
    client = TestClient(app)
    response = client.get("/kpi/llm-cost")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["source"] == "metering"
    assert body["total"]["total_tokens"] == 2650
    assert body["by_month"][0]["key"] == "2026-07"

    # Read-only invariant: no mutating verb on the panel route.
    assert client.post("/kpi/llm-cost").status_code == 405
