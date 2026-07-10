"""Tests for the LLM cost read panel (unit + build_app integration)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.read_api.llm_cost import LlmCostPanel
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"


def _inv(
    *, corr: str, when: datetime, prompt: int, completion: int, cost: str | None
) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=when,
        correlation_id=corr,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
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
        )
    )
    return sink


async def test_render_all_groupings() -> None:
    panel = LlmCostPanel(await _seeded_sink())
    payload = await panel.render(params={})
    assert payload["source"] == "metering"
    assert payload["invocations"] == 3
    assert payload["total"]["cost"] == "0.50"
    assert [row["key"] for row in payload["by_conversation"]] == ["evt-a", "evt-b"]
    assert [row["key"] for row in payload["by_day"]] == ["2026-07-09", "2026-07-10"]
    assert [row["key"] for row in payload["by_month"]] == ["2026-07"]
    # evt-b is unpriced -> transparent
    assert payload["by_conversation"][1]["has_unpriced"] is True


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


def test_panel_metadata() -> None:
    panel = LlmCostPanel(InMemoryMeteringSink())
    assert panel.path == "/kpi/llm-cost"
    assert panel.name == "llm-cost"


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
