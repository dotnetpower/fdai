"""Deterministic LLM usage chat evidence and follow-up continuity."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    is_llm_usage_followup,
    needs_llm_usage,
)
from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore


class _Backend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **_kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "model fallback", "model": "test"}


def _invocation(
    *,
    occurred_at: datetime,
    prompt_tokens: int,
    completion_tokens: int,
    scope: InvocationScope = InvocationScope.OPERATOR_CHAT,
) -> LlmInvocation:
    return LlmInvocation(
        occurred_at=occurred_at,
        correlation_id="chat-example",
        capability_id="t1.judge",
        model_key="example-model",
        tier="T1",
        mode=InvocationMode.ENFORCE,
        usage=TokenUsage(prompt_tokens, completion_tokens),
        usage_scope=scope,
    )


def test_analysis_followup_detection_does_not_capture_explicit_other_domains() -> None:
    assert needs_llm_usage("토큰 사용량에 대해서 알려줘")
    assert is_llm_usage_followup("일주일간 통계를 그래프로 보여줘")
    assert is_llm_usage_followup("모델별로 다시 보여줘")
    assert not is_llm_usage_followup("VM 상태를 그래프로 보여줘")
    assert not is_llm_usage_followup("데이터베이스 통계를 일주일간 보여줘")
    assert not is_llm_usage_followup("오류율을 그래프로 보여줘")
    assert not is_llm_usage_followup("Show the latency as a chart")
    assert not is_llm_usage_followup("compare the two requested datasets")
    assert not is_llm_usage_followup("이 이미지의 목차 내용을 표로 정리해줄래?")
    assert not is_llm_usage_followup("Summarize this attached screenshot as a table")
    assert is_llm_usage_followup("지난주와 비교해줘")


def test_analysis_followup_detection_ignores_read_only_architecture_phrase() -> None:
    # "read-only"/"read only" is FDAI's own pervasive read-only-architecture
    # phrase (appears in nearly every operator question). The bare word "only"
    # inside it must never, by itself, be treated as an LLM-usage chart/table
    # refinement cue - or any unrelated question phrased with "read-only
    # evidence" risks reusing a stale LLM-usage analysis anchor from a prior
    # turn.
    assert not is_llm_usage_followup(
        "Based on current read-only monitoring evidence, is there any active "
        "service outage affecting FDAI-managed services within the configured "
        "Azure scope right now, and how is that determined?"
    )
    assert not is_llm_usage_followup(
        "Using read only inventory evidence, which resources are stopped?"
    )
    assert not is_llm_usage_followup(
        "Out of everything currently in scope, which VMs are actually up and humming right "
        "now? Please list each one with its current power state, based on read-only inventory "
        "evidence only."
    )
    assert not is_llm_usage_followup(
        "Which VMs in the currently configured Azure scope are actually up and running right "
        "now? Please show each one's current power state, drawing only on read-only inventory "
        "evidence."
    )
    assert not is_llm_usage_followup("허용된 범위 내 읽기 전용 근거로 상태를 알려줘.")
    # A genuine chart-refinement cue combined with "only" still routes normally.
    assert is_llm_usage_followup("show only the weekday totals as a chart")


@pytest.mark.parametrize("stream", [False, True])
def test_durable_usage_followup_returns_chart_without_health_or_model_fallback(
    stream: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")
    reader = InMemoryMeteringSink()
    now = datetime.now(UTC)
    observed = tuple(now - timedelta(days=days) for days in (3, 2, 1))
    for occurred_at, tokens in zip(observed, (100, 150, 200), strict=True):
        _record_sync(
            reader,
            _invocation(
                occurred_at=occurred_at,
                prompt_tokens=tokens,
                completion_tokens=20,
            ),
        )
    _record_sync(
        reader,
        _invocation(
            occurred_at=observed[-1],
            prompt_tokens=1_000,
            completion_tokens=0,
            scope=InvocationScope.CONTROL_PLANE,
        ),
    )
    backend = _Backend()
    app = build_app(
        authenticator=_authenticator(),
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            chat=backend,
            llm_usage_reader=reader,
            conversation_history_store=InMemoryConversationHistoryStore(),
        ),
    )

    with TestClient(app) as client:
        first = client.post(
            "/chat",
            json={
                "request_id": "usage-first",
                "session_id": "usage-session",
                "prompt": "채팅 토큰 사용량에 대해서 알려줘",
                "view_context": {"_locale": "ko"},
            },
        ).json()
        assert first["verification"]["authority"] == "server_metering"
        assert first["analysis_context"]["usage_scope"] == "operator_chat"

        response = client.post(
            "/chat/stream" if stream else "/chat",
            json={
                "request_id": "usage-followup-stream" if stream else "usage-followup-json",
                "session_id": "usage-session",
                "prompt": "일주일간 통계를 그래프로 보여줘",
                "view_context": {"_locale": "ko"},
            },
        )
        no_anchor = client.post(
            "/chat",
            json={
                "request_id": f"usage-no-anchor-{stream}",
                "session_id": "fresh-session",
                "prompt": "일주일간 통계를 그래프로 보여줘",
                "analysis_context": {"domain": "llm_usage"},
                "view_context": {
                    "_locale": "ko",
                    "_verified_prior_context": {"status": "verified"},
                },
            },
        ).json()
        regrouped = client.post(
            "/chat",
            json={
                "request_id": f"usage-regrouped-{stream}",
                "session_id": "usage-session",
                "prompt": "최근 2주를 모델별 표로 다시 보여줘",
                "view_context": {"_locale": "ko"},
            },
        ).json()
        unsupported = [
            client.post(
                "/chat",
                json={
                    "request_id": f"usage-unsupported-{index}-{stream}",
                    "session_id": "usage-session",
                    "prompt": prompt,
                    "view_context": {"_locale": "ko"},
                },
            ).json()
            for index, prompt in enumerate(("지난주와 비교해줘", "CSV로 다운로드해줘"))
        ]

    payload = _done_payload(response.text) if stream else response.json()
    assert payload["verification"]["authority"] == "server_metering"
    assert payload["verification"]["reason_code"] == "llm_usage_grounded"
    assert payload["answer_plan"]["format"] == "chart"
    assert payload["analysis_context"]["lookback_days"] == 7
    assert payload["chart_artifact"]["schema_version"] == 1
    assert payload["chart_artifact"]["evidence_refs"] == payload["verification"]["evidence_refs"]
    chart = json.loads(payload["answer"].split("```chart\n", 1)[1].split("\n```", 1)[0])
    assert {key: payload["chart_artifact"][key] for key in chart} == chart
    assert sum(point["value"] for point in chart["data"]) == 510
    assert regrouped["answer_plan"]["format"] == "table"
    assert regrouped["analysis_context"]["lookback_days"] == 14
    assert regrouped["analysis_context"]["group_by"] == "model"
    assert "| example-model | 3 | 450 | 60 | 510 |" in regrouped["answer"]
    assert all(
        item["verification"]["authority"] == "server_conversation_context" for item in unsupported
    )
    assert chart["type"] == "line"
    assert [point["label"] for point in chart["data"]] == [
        item.strftime("%Y-%m-%d") for item in observed
    ]
    assert no_anchor["verification"]["authority"] == "server_conversation_context"
    assert no_anchor["verification"]["reason_code"] == "prior_context_required"
    assert backend.calls == 0


def _authenticator():  # type: ignore[no-untyped-def]
    return build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=RoleResolver(
            group_mapping=GroupMapping(
                reader_group_id="reader-group",
                contributor_group_id="contributor-group",
                approver_group_id="approver-group",
                owner_group_id="owner-group",
                break_glass_group_id="break-glass-group",
            )
        ),
    )


def _record_sync(reader: InMemoryMeteringSink, invocation: LlmInvocation) -> None:
    import asyncio

    asyncio.run(reader.record(invocation))


def _done_payload(text: str) -> dict[str, object]:
    lines = text.splitlines()
    done_index = lines.index("event: done")
    return json.loads(lines[done_index + 1].removeprefix("data: "))
