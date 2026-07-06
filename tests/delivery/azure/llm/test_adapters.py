"""httpx-mocked tests for the Azure OpenAI adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from aiopspilot.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from aiopspilot.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

# Non-empty placeholder for the required Wave 2 `system_prompt` field.
# Real prompts come from ``rule-catalog/prompts/`` via PromptComposer; the
# adapter tests only care that the field is threaded end-to-end.
_TEST_SYSTEM_PROMPT = "unit-test system prompt"


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake in-memory token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _mock_embed_transport(dim: int, *, captured: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1] * dim, "index": 0}]},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_embeddings_success_returns_vector_of_configured_dim() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_embed_transport(dim=1536, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        vector = await adapter.embed("hello world")
    assert len(vector) == 1536
    assert vector[0] == pytest.approx(0.1)
    # URL shape
    req = captured[0]
    assert req.url.path == "/openai/deployments/t1-embedding/embeddings"
    assert req.url.params.get("api-version") == "2024-06-01"
    assert req.headers["Authorization"] == "Bearer test-token"
    assert json.loads(req.content.decode()) == {"input": "hello world"}


@pytest.mark.asyncio
async def test_embeddings_rejects_dim_mismatch() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_embed_transport(dim=8, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(RuntimeError, match="embedding length"):
            await adapter.embed("hi")


@pytest.mark.asyncio
async def test_embeddings_rejects_malformed_body() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(RuntimeError, match="data\\[0\\].embedding"):
            await adapter.embed("hi")


@pytest.mark.asyncio
async def test_embeddings_propagates_http_error() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "quota"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.embed("hi")


def test_embeddings_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="ftp://oai-test.openai.azure.com",
                deployment="t1-embedding",
            ),
        )


# ---------------------------------------------------------------------------
# Cross-check
# ---------------------------------------------------------------------------


def _mock_cross_check_transport(
    content: str, *, captured: list[httpx.Request]
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    return httpx.MockTransport(handler)


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("object-storage.owner-tag.required",),
    )


@pytest.mark.asyncio
async def test_cross_check_parses_structured_json_response() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "remediate.tag-add", "params": {"foo": "bar"}}),
        captured=captured,
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )
        action_type, params = await adapter.propose(_candidate())
    assert action_type == "remediate.tag-add"
    assert params == {"foo": "bar"}
    req = captured[0]
    body = json.loads(req.content.decode())
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512


@pytest.mark.asyncio
async def test_cross_check_rejects_non_json_content() -> None:
    transport = _mock_cross_check_transport("not-json", captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )
        with pytest.raises(RuntimeError, match="non-JSON"):
            await adapter.propose(_candidate())


@pytest.mark.asyncio
async def test_cross_check_rejects_response_without_action_type() -> None:
    transport = _mock_cross_check_transport(json.dumps({"params": {}}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )
        with pytest.raises(RuntimeError, match="action_type"):
            await adapter.propose(_candidate())


@pytest.mark.asyncio
async def test_cross_check_rejects_non_object_params() -> None:
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "x", "params": "not-an-object"}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )
        with pytest.raises(RuntimeError, match="'params'"):
            await adapter.propose(_candidate())


def test_cross_check_config_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError, match="temperature"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
                temperature=3.0,
            ),
        )


def test_cross_check_config_rejects_empty_system_prompt() -> None:
    """Wave 2 invariant: an empty system_prompt is a fail-fast defect.

    The PromptComposer is the sole authorized supplier; a missing or
    empty string means the composition root wired nothing and would
    silently ship a bare user turn to the model.
    """

    with pytest.raises(ValueError, match="system_prompt"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="",
            ),
        )


# ---------------------------------------------------------------------------
# Cross-check tool loop (Wave 2.5-B step 2b)
# ---------------------------------------------------------------------------


class _FakeToolRegistry:
    """Minimal ToolRegistry stub the adapter can iterate over."""

    def __init__(self, artifacts: tuple) -> None:  # noqa: ANN001 - tuple of ToolArtifact
        self._artifacts = artifacts

    def artifacts(self) -> tuple:  # noqa: ANN201
        return self._artifacts

    def get(self, tool_id: str):  # pragma: no cover - unused by the adapter
        raise LookupError(tool_id)


class _RecordingExecutor:
    """Async stub that records dispatches and hands back canned results."""

    def __init__(self, *, responses: dict[str, str]) -> None:
        self._responses = dict(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def dispatch(self, *, tool_id: str, arguments):  # noqa: ANN001
        self.calls.append((tool_id, dict(arguments)))
        from aiopspilot.core.tools import ToolResult

        if tool_id not in self._responses:
            raise KeyError(f"no canned response for {tool_id!r}")
        return ToolResult(
            tool_id=tool_id,
            wrapped_text=self._responses[tool_id],
            raw=self._responses[tool_id],
            cost_usd=0.0,
            latency_ms=0,
        )


def _enforce_tool_artifact(tool_id: str = "rule.query"):
    """Build an enforce-mode ToolArtifact for the adapter to advertise."""

    from aiopspilot.core.prompts.types import PromptMode
    from aiopspilot.core.tools import CapabilityGate, ToolArtifact

    return ToolArtifact(
        id=tool_id,
        version=1,
        description=f"{tool_id} description",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rule_id"],
            "properties": {"rule_id": {"type": "string"}},
        },
        capability_gate=CapabilityGate(
            requires_tier=None,
            requires_novelty_score=None,
            cost_budget_usd_per_call=0.0,
        ),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.ENFORCE,
        provider="RuleCatalogQueryProvider",
        provenance_source="test",
    )


def _shadow_tool_artifact(tool_id: str = "state.query"):
    from aiopspilot.core.prompts.types import PromptMode
    from aiopspilot.core.tools import CapabilityGate, ToolArtifact

    return ToolArtifact(
        id=tool_id,
        version=1,
        description=f"{tool_id} description",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(None, None, None),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.SHADOW,
        provider="StateStoreQueryProvider",
        provenance_source="test",
    )


def _scripted_transport(
    responses: list[dict], *, captured: list[httpx.Request]
) -> httpx.MockTransport:
    """MockTransport that returns responses in order, per POST."""

    counter = {"i": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        i = counter["i"]
        counter["i"] = i + 1
        if i >= len(responses):
            raise AssertionError(f"scripted transport ran out of responses at request #{i}")
        return httpx.Response(200, json={"choices": [{"message": responses[i]}]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_cross_check_advertises_only_enforce_tools() -> None:
    """Shadow-mode tools MUST NOT appear in the OpenAI ``tools`` param
    even when the adapter is wired to a ToolRegistry that lists them."""

    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "noop", "params": {}}), captured=captured
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(
                artifacts=(
                    _enforce_tool_artifact("rule.query"),
                    _shadow_tool_artifact("state.query"),
                )
            ),
            tool_executor=_RecordingExecutor(responses={}),
        )
        await adapter.propose(_candidate())
    body = json.loads(captured[0].content.decode())
    tool_names = [t["function"]["name"] for t in body["tools"]]
    assert tool_names == ["rule_query"]  # dot-encoded, no shadow tool


@pytest.mark.asyncio
async def test_cross_check_omits_tools_when_only_shadow_available() -> None:
    """Registry with zero enforce tools => the adapter does NOT set
    ``tools`` or ``tool_choice`` (avoids advertising 'no tools')."""

    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "noop", "params": {}}), captured=captured
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(artifacts=(_shadow_tool_artifact("state.query"),)),
            tool_executor=_RecordingExecutor(responses={}),
        )
        await adapter.propose(_candidate())
    body = json.loads(captured[0].content.decode())
    assert "tools" not in body
    assert "tool_choice" not in body


@pytest.mark.asyncio
async def test_cross_check_completes_tool_loop() -> None:
    """A tool_calls response -> executor dispatch -> final JSON answer."""

    captured: list[httpx.Request] = []
    executor = _RecordingExecutor(
        responses={"rule.query": '<tool_result trusted="false">{"severity":"high"}</tool_result>'}
    )
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "rule_query",
                        "arguments": json.dumps({"rule_id": "example.rule"}),
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": json.dumps({"action_type": "remediate.tag-add", "params": {"tag": "owner"}}),
        },
    ]
    transport = _scripted_transport(scripted, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(artifacts=(_enforce_tool_artifact("rule.query"),)),
            tool_executor=executor,
        )
        action_type, params = await adapter.propose(_candidate())

    assert action_type == "remediate.tag-add"
    assert params == {"tag": "owner"}
    assert executor.calls == [("rule.query", {"rule_id": "example.rule"})]
    # Two model round-trips: initial + follow-up.
    assert len(captured) == 2

    # The follow-up request MUST carry the assistant tool_calls turn AND
    # the tool result message so the model has full context.
    follow_up = json.loads(captured[1].content.decode())
    roles = [m["role"] for m in follow_up["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert follow_up["messages"][-1]["tool_call_id"] == "call_1"
    assert "severity" in follow_up["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_cross_check_max_tool_iterations_forces_hil() -> None:
    """Model that keeps calling tools past the ceiling MUST fail closed."""

    captured: list[httpx.Request] = []
    executor = _RecordingExecutor(responses={"rule.query": "irrelevant"})
    # Every response asks for another tool call, so the loop exhausts
    # the budget without ever producing a final answer.
    tool_call_response = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_x",
                "type": "function",
                "function": {
                    "name": "rule_query",
                    "arguments": json.dumps({"rule_id": "loop"}),
                },
            }
        ],
    }
    scripted = [tool_call_response] * 5
    transport = _scripted_transport(scripted, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
                max_tool_iterations=2,
            ),
            tool_registry=_FakeToolRegistry(artifacts=(_enforce_tool_artifact("rule.query"),)),
            tool_executor=executor,
        )
        with pytest.raises(RuntimeError, match="max_tool_iterations=2"):
            await adapter.propose(_candidate())


@pytest.mark.asyncio
async def test_cross_check_rejects_unknown_tool_function_name() -> None:
    """A hallucinated function name MUST fail closed - the adapter never
    dispatches to a tool the model was not told exists."""

    captured: list[httpx.Request] = []
    executor = _RecordingExecutor(responses={})
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "hallucinated",
                    "type": "function",
                    "function": {
                        "name": "delete_everything",
                        "arguments": "{}",
                    },
                }
            ],
        }
    ]
    transport = _scripted_transport(scripted, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(artifacts=(_enforce_tool_artifact("rule.query"),)),
            tool_executor=executor,
        )
        with pytest.raises(RuntimeError, match="unknown tool function"):
            await adapter.propose(_candidate())
    assert executor.calls == []


@pytest.mark.asyncio
async def test_cross_check_rejects_non_json_tool_arguments() -> None:
    """Malformed arguments from the model MUST fail closed before hitting
    the executor's schema validation (belt-and-braces)."""

    captured: list[httpx.Request] = []
    executor = _RecordingExecutor(responses={})
    scripted = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "rule_query",
                        "arguments": "not-a-json-object",
                    },
                }
            ],
        }
    ]
    transport = _scripted_transport(scripted, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(artifacts=(_enforce_tool_artifact("rule.query"),)),
            tool_executor=executor,
        )
        with pytest.raises(RuntimeError, match="non-JSON arguments"):
            await adapter.propose(_candidate())
    assert executor.calls == []


def test_cross_check_rejects_half_wired_tool_setup() -> None:
    """Passing one of ``tool_registry`` / ``tool_executor`` without the
    other MUST fail-fast at construction so a config bug cannot leave
    the adapter with a manifest but no dispatch (or vice versa)."""

    with pytest.raises(ValueError, match="tool_registry and tool_executor"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            tool_registry=_FakeToolRegistry(artifacts=()),
            tool_executor=None,
        )


def test_cross_check_rejects_negative_max_tool_iterations() -> None:
    with pytest.raises(ValueError, match="max_tool_iterations"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
                max_tool_iterations=-1,
            ),
        )


# ---------------------------------------------------------------------------
# Cross-check per-event composition (Wave 3 step C-2)
# ---------------------------------------------------------------------------


class _RecordingComposer:
    """Minimal :class:`PromptComposer` stub.

    Every call records ``(capability_id, scope)`` on ``.calls`` and
    returns a :class:`ComposedPrompt` whose ``system_text`` is a
    formatted, per-call unique string so tests can prove the adapter
    used the composed text (not the fallback).
    """

    def __init__(self) -> None:
        from aiopspilot.core.operator_memory import OperatorScope
        from aiopspilot.core.prompts.types import ComposedPrompt

        self._ComposedPrompt = ComposedPrompt
        self._OperatorScope = OperatorScope
        self.calls: list[tuple[str, object]] = []

    async def compose(
        self, *, capability_id: str, scope: object = None
    ) -> object:  # ComposedPrompt but avoiding forward-ref juggling in tests
        from aiopspilot.core.prompts.types import LayerRef, PromptLayer

        self.calls.append((capability_id, scope))
        marker = "scoped" if scope is not None else "no-scope"
        text = f"composed[{capability_id}][{marker}][{len(self.calls)}]"
        return self._ComposedPrompt(
            system_text=text,
            layer_manifest=(
                LayerRef(id="base", version=1, layer=PromptLayer.BASE, token_estimate=1),
            ),
            token_estimate=1,
        )


class _RaisingComposer:
    async def compose(
        self, *, capability_id: str, scope: object = None
    ) -> object:  # pragma: no cover - never returns
        raise RuntimeError("catalog unavailable")


@pytest.mark.asyncio
async def test_cross_check_composes_prompt_per_event() -> None:
    """When ``prompt_composer`` is wired, each call re-composes.

    The captured request MUST carry the composer's per-call text
    (proving the adapter did not fall back to ``config.system_prompt``)
    and the composer MUST see the wired ``capability_id``.
    """

    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "remediate.tag-add", "params": {}}),
        captured=captured,
    )
    composer = _RecordingComposer()
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unused-fallback",
            ),
            prompt_composer=composer,  # type: ignore[arg-type]
            capability_id="t2.reasoner.primary",
        )
        await adapter.propose(_candidate())
        await adapter.propose(_candidate())
    assert len(composer.calls) == 2
    assert composer.calls[0][0] == "t2.reasoner.primary"
    assert composer.calls[0][1] is None  # no scope_resolver wired
    body1 = json.loads(captured[0].content.decode())
    body2 = json.loads(captured[1].content.decode())
    system_1 = body1["messages"][0]
    system_2 = body2["messages"][0]
    assert system_1["role"] == "system"
    assert system_1["content"] == "composed[t2.reasoner.primary][no-scope][1]"
    assert system_2["content"] == "composed[t2.reasoner.primary][no-scope][2]"


@pytest.mark.asyncio
async def test_cross_check_scope_resolver_feeds_composer() -> None:
    """When ``scope_resolver`` is wired, the derived scope reaches the composer."""

    from aiopspilot.core.operator_memory import OperatorScope

    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "x", "params": {}}), captured=captured
    )
    composer = _RecordingComposer()

    def resolve(candidate: QualityCandidate) -> OperatorScope | None:
        return OperatorScope(resource_group_ref="rg-example", resource_ref=None)

    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-secondary",
                system_prompt="unused-fallback",
            ),
            prompt_composer=composer,  # type: ignore[arg-type]
            capability_id="t2.reasoner.secondary",
            scope_resolver=resolve,
        )
        await adapter.propose(_candidate())
    (call_capability, call_scope) = composer.calls[0]
    assert call_capability == "t2.reasoner.secondary"
    assert isinstance(call_scope, OperatorScope)
    assert call_scope.resource_group_ref == "rg-example"
    body = json.loads(captured[0].content.decode())
    assert body["messages"][0]["content"] == "composed[t2.reasoner.secondary][scoped][1]"


@pytest.mark.asyncio
async def test_cross_check_uses_fallback_when_composer_not_wired() -> None:
    """Backwards-compat: no composer -> the static system_prompt is sent."""

    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "x", "params": {}}), captured=captured
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
        )
        await adapter.propose(_candidate())
    body = json.loads(captured[0].content.decode())
    assert body["messages"][0]["content"] == _TEST_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_cross_check_composer_failure_raises_runtime_error() -> None:
    """A composer that raises MUST surface as RuntimeError (routes to HIL),
    NOT silently degrade to the fallback text - which would ship a stale
    prompt without operator memory or fresh canary tokens."""

    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "x", "params": {}}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt="unused-fallback",
            ),
            prompt_composer=_RaisingComposer(),  # type: ignore[arg-type]
            capability_id="t2.reasoner.primary",
        )
        with pytest.raises(RuntimeError, match="prompt composition failed"):
            await adapter.propose(_candidate())


def test_cross_check_rejects_half_wired_composer() -> None:
    """capability_id without composer (or the reverse) is a fail-fast defect."""

    composer = _RecordingComposer()
    with pytest.raises(ValueError, match="prompt_composer and capability_id"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            prompt_composer=composer,  # type: ignore[arg-type]
            # capability_id missing on purpose
        )
    with pytest.raises(ValueError, match="prompt_composer and capability_id"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            capability_id="t2.reasoner.primary",
            # prompt_composer missing on purpose
        )


def test_cross_check_rejects_empty_capability_id_when_composer_wired() -> None:
    with pytest.raises(ValueError, match="capability_id"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            prompt_composer=_RecordingComposer(),  # type: ignore[arg-type]
            capability_id="   ",
        )


def test_cross_check_rejects_scope_resolver_without_composer() -> None:
    def resolve(candidate: QualityCandidate) -> object:  # pragma: no cover - never called
        return None

    with pytest.raises(ValueError, match="scope_resolver requires prompt_composer"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                system_prompt=_TEST_SYSTEM_PROMPT,
            ),
            scope_resolver=resolve,  # type: ignore[arg-type]
        )
