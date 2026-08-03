from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation.answer_plan import AnswerIntent, AnswerSection, build_answer_plan
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.operator_api.routes.chat_backend_openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.operator_api.routes.chat_backend_router import LatencyRoutedChatBackend
from fdai.delivery.operator_api.routes.chat_evidence_pipeline import resolve_parallel_chat_evidence
from fdai.delivery.operator_api.routes.chat_intent_graph import parse_intent_graph
from fdai.delivery.operator_api.routes.chat_model_trace import (
    activate_model_trace,
    deactivate_model_trace,
    snapshot_model_trace,
)
from fdai.delivery.operator_api.routes.chat_stream import make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_tools import ReadModelChatTools
from fdai.delivery.operator_api.routes.chat_turn_plan import (
    BackendTurnPlanner,
    TurnKind,
    TurnPlan,
    TurnTool,
    agent_turn_tools,
    apply_turn_plan_to_answer_plan,
    default_read_turn_tools,
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


class _AnswerBackend:
    def __init__(self) -> None:
        self.context: dict[str, object] = {}
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        raw_context = kwargs["view_context"]
        assert isinstance(raw_context, dict)
        self.context = raw_context
        return {"answer": "It is created only after confirmation.", "model": "test-mini"}


class _Planner:
    def __init__(self, result: TurnPlan | None = None) -> None:
        self.calls = 0
        self.result = result or parse_turn_plan(_plan())

    async def plan_turn(self, **_kwargs: object) -> TurnPlan:
        self.calls += 1
        return self.result


class _GraphPlanner:
    def __init__(self, tools: tuple[TurnTool, ...]) -> None:
        self.calls = 0
        self.result = parse_intent_graph(
            {
                "schema_version": 2,
                "goals": [
                    {
                        "goal_id": "incidents",
                        "intent": "status",
                        "capability": "list_incidents",
                        "arguments": {"status": "active"},
                        "depends_on": [],
                        "evidence_mode": "operational",
                        "freshness_required": True,
                        "confidence": 0.94,
                        "alternatives": [],
                    },
                    {
                        "goal_id": "kpi",
                        "intent": "comparison",
                        "capability": "get_kpi",
                        "arguments": {},
                        "depends_on": ["incidents"],
                        "evidence_mode": "screen",
                        "freshness_required": True,
                        "confidence": 0.9,
                        "alternatives": [],
                    },
                ],
                "clarification": None,
                "confidence": 0.91,
                "action_posture": "advise_only",
            },
            tools=tools,
        )

    async def plan_turn(self, **_kwargs: object):
        self.calls += 1
        return self.result


class _FailingKeywordResolver:
    async def resolve(self, *_args: object, **_kwargs: object) -> dict[str, object] | None:
        raise AssertionError("legacy keyword resolver must not run for a semantic plan")


class _PlannedResolver:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> Mapping[str, Any] | None:
        self.calls += 1
        return {
            "tool": tool_name,
            "authority": "server_read_model",
            "result": {
                "arguments": arguments,
                "principal_id": principal_id,
                "secret_detail": "server-context-only",
                "evidence_refs": [f"tool:{tool_name}"],
            },
        }


async def _allow(_request: Request) -> str:
    return "reader-1"


def _read_tools() -> tuple[TurnTool, ...]:
    return (
        TurnTool(
            name="query_incidents",
            description="Read incident summaries.",
            side_effect_class="read",
            argument_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "resolved", "all"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
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


def test_nullable_optional_argument_placeholders_are_removed() -> None:
    plan = parse_turn_plan(
        _plan(
            kind="read_tool",
            tool_name="query_incidents",
            arguments={"status": "active", "limit": None},
        )
    )

    assert plan.arguments == {"status": "active"}


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

    trace_scope = activate_model_trace(True)
    try:
        plan = await BackendTurnPlanner(backend).plan_turn(
            prompt="show active incidents",
            tools=_read_tools(),
            history=(),
        )
        trace = snapshot_model_trace(trace_scope.collector)
    finally:
        deactivate_model_trace(trace_scope)

    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    argument_variants = schema["properties"]["arguments"]["anyOf"]
    incident_arguments = next(
        variant
        for variant in argument_variants
        if set(variant.get("properties", {})) == {"status", "limit"}
    )
    assert incident_arguments["additionalProperties"] is False
    assert incident_arguments["required"] == ["status", "limit"]
    assert set(incident_arguments["properties"]["status"]["type"]) == {"string", "null"}
    assert incident_arguments["properties"]["status"]["enum"] == [
        "active",
        "resolved",
        "all",
        None,
    ]
    assert trace is not None
    assert trace["calls"][0]["kind"] == "structured:fdai_turn_plan"
    assert "query_incidents" in trace["calls"][0]["response"]["content"]
    assert plan.tool_name == "query_incidents"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["azure-ad", "openai"])
async def test_real_backends_reject_length_truncated_structured_completion(
    provider: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": json.dumps(_plan())},
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

    with pytest.raises(HTTPException) as exc_info:
        await BackendTurnPlanner(backend).plan_turn(
            prompt="show active incidents",
            tools=_read_tools(),
            history=(),
        )

    assert exc_info.value.status_code == 502
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


def test_default_turn_manifest_exposes_only_read_capabilities() -> None:
    tools = default_read_turn_tools()

    assert tools
    assert all(tool.side_effect_class == "read" for tool in tools)


def test_agent_turn_manifest_uses_canonical_pantheon_names() -> None:
    tools = agent_turn_tools()

    assert len(tools) == 15
    assert all(tool.name.startswith("agent:") for tool in tools)
    assert all(tool.side_effect_class == "read" for tool in tools)


def test_semantic_answer_intent_replaces_keyword_intent_and_sections() -> None:
    keyword_plan = build_answer_plan("why did this happen?")
    semantic = parse_turn_plan(_plan(answer_intent="comparison"))

    resolved = apply_turn_plan_to_answer_plan(keyword_plan, semantic)

    assert keyword_plan.intent is AnswerIntent.WHY
    assert resolved.intent is AnswerIntent.COMPARISON
    assert resolved.sections == (
        AnswerSection.CRITERIA,
        AnswerSection.ITEMS,
        AnswerSection.TRADE_OFFS,
        AnswerSection.RECOMMENDATION,
    )
    assert resolved.detail_level is keyword_plan.detail_level
    assert resolved.format is keyword_plan.format


@pytest.mark.parametrize("stream", [False, True])
def test_chat_routes_attach_shadow_semantic_plan(stream: bool) -> None:
    backend = _AnswerBackend()
    planner = _Planner()
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=default_read_turn_tools(),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=default_read_turn_tools(),
        )
    )
    app = Starlette(routes=[route])
    path = "/chat/stream" if stream else "/chat"

    response = TestClient(app).post(path, json={"prompt": "Incident 는 자동으로 생성되나?"})

    assert response.status_code == 200
    assert planner.calls == 1
    assert backend.context["_turn_plan"] == {
        "kind": "answer",
        "answer_intent": "open_question",
        "tool_name": None,
        "action_type": None,
        "arguments": {},
        "clarification": None,
        "confidence": 0.91,
        "requires_confirmation": False,
    }


@pytest.mark.parametrize("stream", [False, True])
def test_chat_routes_execute_hierarchical_intent_graph(stream: bool) -> None:
    backend = _AnswerBackend()
    tools = (
        TurnTool("list_incidents", "Read incidents.", "read", {"type": "object"}),
        TurnTool("get_kpi", "Read KPI values.", "read", {"type": "object"}),
    )
    planner = _GraphPlanner(tools)
    resolver = _PlannedResolver()
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=resolver,
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=resolver,
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={"prompt": "show incidents and compare the KPI"},
    )

    assert response.status_code == 200
    assert planner.calls == 1
    assert resolver.calls == 2
    assert backend.calls == 0
    assert backend.context == {}
    payload = response.text if stream else json.dumps(response.json())
    assert '"schema_version": 2' in payload or '"schema_version":2' in payload
    assert '"status": "completed"' in payload or '"status":"completed"' in payload
    assert '"goal_id": "incidents"' in payload or '"goal_id":"incidents"' in payload
    assert '"goal_id": "kpi"' in payload or '"goal_id":"kpi"' in payload
    assert '"intent_graph"' in payload
    assert '"intent_graph_evidence"' in payload
    assert '"evidence_mode":"mixed_grounded"' in payload.replace(" ", "")
    assert '"evidence_refs"' in payload
    assert "server-context-only" not in payload


@pytest.mark.parametrize("stream", [False, True])
def test_unavailable_intent_graph_cannot_become_empty_screen_answer(stream: bool) -> None:
    class UnavailableResolver:
        async def resolve_planned(
            self,
            tool_name: str,
            arguments: Mapping[str, object],
            *,
            principal_id: str,
        ) -> None:
            del tool_name, arguments, principal_id
            return None

    backend = _AnswerBackend()
    tools = (
        TurnTool("list_incidents", "Read incidents.", "read", {"type": "object"}),
        TurnTool("get_kpi", "Read KPI values.", "read", {"type": "object"}),
    )
    planner = _GraphPlanner(tools)
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=UnavailableResolver(),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=UnavailableResolver(),
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={
            "prompt": "List resources in this group with type, region, and state.",
            "view_context": {},
        },
    )

    assert response.status_code == 200
    assert backend.calls == 0
    payload = response.text if stream else json.dumps(response.json())
    assert "server_intent_graph" in payload
    assert "intent_graph_unavailable" in payload
    assert "client_snapshot" not in payload
    assert "No resources are shown" not in payload


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "prompt",
    [
        "Are all FDAI services healthy?",
        "FDAI 서비스가 모두 정상인가?",
    ],
)
def test_hierarchical_planner_owns_multilingual_health_intent(
    stream: bool,
    prompt: str,
) -> None:
    backend = _AnswerBackend()
    tools = (
        TurnTool("list_incidents", "Read incidents.", "read", {"type": "object"}),
        TurnTool("get_kpi", "Read KPI values.", "read", {"type": "object"}),
    )
    planner = _GraphPlanner(tools)
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=_PlannedResolver(),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=tools,
            planned_tool_resolver=_PlannedResolver(),
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={"prompt": prompt},
    )

    assert response.status_code == 200
    assert planner.calls == 1


@pytest.mark.parametrize("stream", [False, True])
def test_graph_draft_rechecks_current_capability_manifest(stream: bool) -> None:
    action = TurnTool(
        "ops.restart-service",
        "Draft a restart.",
        "write",
        {
            "type": "object",
            "properties": {"resource_ref": {"type": "string"}},
            "required": ["resource_ref"],
            "additionalProperties": False,
        },
    )
    graph = parse_intent_graph(
        {
            "schema_version": 2,
            "goals": [
                {
                    "goal_id": "restart",
                    "intent": "proposal",
                    "capability": "ops.restart-service",
                    "arguments": {"resource_ref": "service-example"},
                    "depends_on": [],
                    "evidence_mode": "operational",
                    "freshness_required": True,
                    "confidence": 0.9,
                    "alternatives": [],
                }
            ],
            "clarification": None,
            "confidence": 0.9,
            "action_posture": "draft_only",
        },
        tools=(action,),
    )

    class DraftPlanner:
        async def plan_turn(self, **_kwargs: object):
            return graph

    manifest_reads = 0

    def current_tools() -> tuple[TurnTool, ...]:
        nonlocal manifest_reads
        manifest_reads += 1
        return (action,) if manifest_reads == 1 else ()

    route = (
        make_chat_stream_route(
            backend=_AnswerBackend(),
            authorize=_allow,
            turn_planner=DraftPlanner(),
            turn_tools=current_tools,
        )
        if stream
        else make_chat_route(
            backend=_AnswerBackend(),
            authorize=_allow,
            turn_planner=DraftPlanner(),
            turn_tools=current_tools,
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={"prompt": "Draft a restart"},
    )

    assert manifest_reads == 2
    assert "draft capability is no longer available" in response.text
    assert '"action_draft"' not in response.text
    assert response.status_code == (200 if stream else 409)


@pytest.mark.parametrize("stream", [False, True])
def test_chat_write_plan_returns_draft_without_calling_answer_backend(stream: bool) -> None:
    backend = _AnswerBackend()
    planner = _Planner(
        parse_turn_plan(
            _plan(
                kind="action_draft",
                action_type="ops.restart-service",
                arguments={"resource_id": "svc-1"},
            )
        )
    )
    action_tool = TurnTool(
        name="ops.restart-service",
        description="Draft a restart.",
        side_effect_class="write",
        argument_schema={"type": "object"},
    )
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=(action_tool,),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=(action_tool,),
        )
    )
    path = "/chat/stream" if stream else "/chat"

    response = TestClient(Starlette(routes=[route])).post(
        path,
        json={"prompt": "restart svc-1", "request_id": "request-1"},
    )

    assert response.status_code == 200
    assert backend.calls == 0
    payload = response.text if stream else json.dumps(response.json())
    assert '"action_type":"ops.restart-service"' in payload.replace(" ", "")
    assert '"resource_id":"svc-1"' in payload.replace(" ", "")


@pytest.mark.parametrize("stream", [False, True])
def test_bound_incident_context_skips_confirmation_draft_before_evidence(stream: bool) -> None:
    backend = _AnswerBackend()
    planner = _Planner(
        parse_turn_plan(
            _plan(
                kind="action_draft",
                action_type="ops.restart-service",
                arguments={"resource_id": "svc-1"},
            )
        )
    )

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ) -> Mapping[str, object]:
            del prompt
            assert conversation_context == {
                "kind": "incident",
                "incident_id": "incident-1",
                "correlation_id": "corr-incident",
            }
            return {
                "authority": "server_read_model",
                "status": "matched",
                "incident_query_intent": "unknowns",
                "selected_incident": {"correlation_id": "corr-incident"},
                "grounded_hypotheses": [],
                "audit_evidence": [],
            }

    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            evidence_resolver=OperationalResolver(),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            evidence_resolver=OperationalResolver(),
        )
    )
    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={
            "prompt": "What remains unknown?",
            "conversation_context": {
                "kind": "incident",
                "incident_id": "incident-1",
                "correlation_id": "corr-incident",
            },
        },
    )

    assert response.status_code == 200
    assert planner.calls == 0
    assert backend.calls == 0
    payload = response.text if stream else json.dumps(response.json())
    assert '"action_draft"' not in payload
    assert '"authority":"server_read_model"' in payload.replace(" ", "")


@pytest.mark.parametrize("stream", [False, True])
def test_screen_selected_incident_skips_confirmation_draft_before_evidence(
    stream: bool,
) -> None:
    backend = _AnswerBackend()
    planner = _Planner(
        parse_turn_plan(
            _plan(
                kind="action_draft",
                action_type="ops.restart-service",
                arguments={"resource_id": "svc-1"},
            )
        )
    )

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ) -> Mapping[str, object]:
            del prompt
            assert conversation_context == {
                "kind": "incident",
                "incident_id": "incident-1",
                "correlation_id": "corr-incident",
            }
            return {
                "authority": "server_read_model",
                "status": "matched",
                "incident_query_intent": "unknowns",
                "selected_incident": {"correlation_id": "corr-incident"},
                "grounded_hypotheses": [],
                "audit_evidence": [],
            }

    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            evidence_resolver=OperationalResolver(),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            evidence_resolver=OperationalResolver(),
        )
    )
    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={
            "prompt": "What remains unknown for this selected incident?",
            "view_context": {
                "routeId": "incidents",
                "records": {
                    "selected_incident": [
                        {
                            "incident_id": "incident-1",
                            "correlation_id": "corr-incident",
                            "title": "Selected incident",
                        }
                    ]
                },
            },
        },
    )

    assert response.status_code == 200
    assert planner.calls == 0
    assert backend.calls == 0
    payload = response.text if stream else json.dumps(response.json())
    assert '"action_draft"' not in payload
    assert '"authority":"server_read_model"' in payload.replace(" ", "")


@pytest.mark.parametrize("stream", [False, True])
def test_screen_incident_context_keeps_explicit_action_draft_available(stream: bool) -> None:
    backend = _AnswerBackend()
    planner = _Planner(
        parse_turn_plan(
            _plan(
                kind="action_draft",
                action_type="ops.restart-service",
                arguments={"resource_id": "svc-1"},
            )
        )
    )
    action_tool = TurnTool(
        name="ops.restart-service",
        description="Draft a restart.",
        side_effect_class="write",
        argument_schema={"type": "object"},
    )
    route = (
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=(action_tool,),
        )
        if stream
        else make_chat_route(
            backend=backend,
            authorize=_allow,
            turn_planner=planner,
            turn_tools=(action_tool,),
        )
    )
    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={
            "prompt": "Draft a restart action for this selected incident.",
            "view_context": {
                "routeId": "incidents",
                "records": {
                    "selected_incident": [
                        {
                            "incident_id": "incident-1",
                            "correlation_id": "corr-incident",
                            "title": "Selected incident",
                        }
                    ]
                },
            },
        },
    )

    assert response.status_code == 200
    assert planner.calls == 1
    assert backend.calls == 0
    payload = response.text if stream else json.dumps(response.json())
    assert '"action_draft"' in payload
    assert '"action_type":"ops.restart-service"' in payload.replace(" ", "")


@pytest.mark.asyncio
async def test_read_model_tools_execute_structured_plan_without_prompt_matching() -> None:
    resolver = ReadModelChatTools(InMemoryConsoleReadModel())

    evidence = await resolver.resolve_planned(
        "list_incidents",
        {"status": "active", "limit": 5},
        principal_id="reader-1",
    )

    assert evidence is not None
    assert evidence["tool"] == "list_incidents"
    assert evidence["authority"] == "server_read_model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"status": "unknown"},
        {"limit": 0},
        {"limit": 101},
        {"unexpected": True},
    ],
)
async def test_read_model_tools_reject_invalid_planned_arguments(
    arguments: dict[str, object],
) -> None:
    resolver = ReadModelChatTools(InMemoryConsoleReadModel())

    with pytest.raises(ValueError, match="planned tool"):
        await resolver.resolve_planned(
            "list_incidents",
            arguments,
            principal_id="reader-1",
        )


@pytest.mark.asyncio
async def test_answer_plan_bypasses_legacy_keyword_evidence_routing() -> None:
    context = {"_turn_plan": parse_turn_plan(_plan()).to_dict()}

    enriched = await resolve_parallel_chat_evidence(
        request_id="request-1",
        prompt="Incident 는 자동으로 생성되나?",
        view_context=context,
        user_id="reader-1",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=_FailingKeywordResolver(),
        planned_tool_resolver=_PlannedResolver(),
        evidence_resolver=None,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=_ignore_progress,
    )

    assert "_tool_evidence" not in enriched


@pytest.mark.asyncio
async def test_read_plan_calls_only_structured_resolver() -> None:
    resolver = _PlannedResolver()
    context = {
        "_turn_plan": parse_turn_plan(
            _plan(
                kind="read_tool",
                tool_name="list_incidents",
                arguments={"status": "active"},
            )
        ).to_dict()
    }

    enriched = await resolve_parallel_chat_evidence(
        request_id="request-2",
        prompt="whatever phrasing the operator used",
        view_context=context,
        user_id="reader-1",
        session_id="session-1",
        conversation_context=None,
        target_agent=None,
        tool_resolver=_FailingKeywordResolver(),
        planned_tool_resolver=resolver,
        evidence_resolver=None,
        agent_delegate=None,
        web_search_resolver=None,
        progress_observer=_ignore_progress,
    )

    assert resolver.calls == 1
    assert enriched["_tool_evidence"]["tool"] == "list_incidents"


async def _ignore_progress(_event: object) -> None:
    return None
