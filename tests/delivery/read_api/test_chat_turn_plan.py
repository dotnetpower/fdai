from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.read_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.read_api.routes.chat_backend_openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.read_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.read_api.routes.chat_turn_plan import (
    BackendTurnPlanner,
    TurnKind,
    TurnTool,
    parse_turn_plan,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _StructuredBackend:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.user_content = ""

    async def complete_structured(self, **kwargs: object) -> dict[str, object]:
        self.user_content = str(kwargs["user_content"])
        return self.result

    async def answer(self, **_kwargs: object) -> dict[str, object]:
        return {"answer": "test", "model": "structured-test"}


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
            audience=audience,
        )


def _read_tools() -> tuple[TurnTool, ...]:
    return (
        TurnTool(
            name="query_incidents",
            description="Read incident summaries.",
            side_effect_class="read",
            argument_schema={"type": "object"},
        ),
    )


def _plan(**overrides: object) -> dict[str, object]:
    return {
        "kind": "answer",
        "answer_intent": "open_question",
        "tool_name": None,
        "action_type": None,
        "arguments": {},
        "clarification": None,
        "confidence": 0.91,
        **overrides,
    }


def test_question_plan_has_no_write_authority() -> None:
    plan = parse_turn_plan(_plan())

    assert plan.kind is TurnKind.ANSWER
    assert plan.requires_confirmation is False


def test_action_plan_is_always_a_confirmation_required_draft() -> None:
    plan = parse_turn_plan(
        _plan(
            kind="action_draft",
            action_type="ops.restart-service",
            arguments={"resource_id": "vm-1"},
        )
    )

    assert plan.kind is TurnKind.ACTION_DRAFT
    assert plan.requires_confirmation is True


@pytest.mark.parametrize(
    "raw",
    [
        _plan(kind="answer", action_type="ops.restart-service"),
        _plan(kind="read_tool", tool_name=None),
        _plan(kind="incident_draft", action_type="ops.restart-service"),
        _plan(kind="clarification", clarification=None),
        _plan(kind="answer", arguments={"resource_id": "vm-1"}),
        {**_plan(), "unexpected": True},
    ],
)
def test_invalid_or_overprivileged_model_plans_are_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="turn plan"):
        parse_turn_plan(raw)


@pytest.mark.asyncio
async def test_backend_planner_accepts_only_server_listed_read_tool() -> None:
    backend = _StructuredBackend(
        _plan(kind="read_tool", tool_name="query_incidents", arguments={"status": "active"})
    )
    planner = BackendTurnPlanner(backend)

    plan = await planner.plan_turn(
        prompt="활성 인시던트를 보여줘",
        tools=_read_tools(),
        history=(),
    )

    assert plan.tool_name == "query_incidents"
    assert "활성 인시던트를 보여줘" in backend.user_content


@pytest.mark.asyncio
async def test_backend_planner_rejects_unlisted_or_wrong_side_effect_selection() -> None:
    unlisted = BackendTurnPlanner(
        _StructuredBackend(_plan(kind="read_tool", tool_name="query_secrets"))
    )
    write_as_read = BackendTurnPlanner(
        _StructuredBackend(_plan(kind="read_tool", tool_name="ops.restart-service"))
    )
    tools = (
        TurnTool(
            name="ops.restart-service",
            description="Draft a restart proposal.",
            side_effect_class="write",
            argument_schema={"type": "object"},
        ),
    )

    with pytest.raises(ValueError, match="unavailable capability"):
        await unlisted.plan_turn(prompt="show secrets", tools=tools, history=())
    with pytest.raises(ValueError, match="write capability"):
        await write_as_read.plan_turn(prompt="restart status", tools=tools, history=())


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["azure-ad", "openai"])
async def test_real_backends_send_strict_turn_plan_schema(provider: str) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                _plan(kind="read_tool", tool_name="query_incidents")
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend: object
    if provider == "azure-ad":
        backend = AzureAdChatBackend(
            endpoint="https://example.openai.azure.com",
            deployment="narrator-mini",
            identity=_Identity(),
            http_client=client,
        )
    else:
        backend = OpenAiCompatibleChatBackend(
            config=OpenAiCompatibleChatBackendConfig(
                provider="openai",
                base_url="https://models.example.com",
                api_key="test-key",  # noqa: S106 - synthetic credential
                model="narrator-mini",
            ),
            http_client=client,
        )

    plan = await BackendTurnPlanner(backend).plan_turn(
        prompt="show active incidents",
        tools=_read_tools(),
        history=(),
    )

    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert plan.tool_name == "query_incidents"
    await client.aclose()


@pytest.mark.asyncio
async def test_latency_router_fails_over_for_structured_completion() -> None:
    unavailable = _StructuredBackend(_plan())

    async def fail(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("planner unavailable")

    unavailable.complete_structured = fail  # type: ignore[method-assign]
    available = _StructuredBackend(_plan())
    router = LatencyRoutedChatBackend(
        candidates=[("a", unavailable), ("b", available)],
        turn_timeout_seconds=1.0,
    )

    plan = await BackendTurnPlanner(router).plan_turn(
        prompt="Incident 는 자동으로 생성되나?",
        tools=_read_tools(),
        history=(),
    )

    assert plan.kind is TurnKind.ANSWER
