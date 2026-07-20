"""AzureOpenAICrossCheckModel - httpx-based T2 cross-check client.

Implements :class:`~fdai.core.quality_gate.gate.CrossCheckModel` by
calling Azure OpenAI ``chat/completions`` with structured JSON output.
The response MUST contain ``action_type`` and ``params``; anything else
raises so the caller cannot silently accept a malformed proposal - this
is the "verifier is the authority" invariant from
``docs/roadmap/architecture/llm-strategy.md § T2 - Reasoning Tier``.

Wave 2.5-B step 2b adds optional function-calling. When the composition
root supplies a :class:`ToolRegistry` + :class:`ToolExecutor` pair, the
adapter advertises every ``enforce`` mode tool via the OpenAI ``tools``
parameter and routes any model-issued ``tool_calls`` through the
executor before continuing the conversation. The loop is bounded by
``max_tool_iterations`` and every failure raises so the caller can
route to HIL.

Wave 3 step C-2 adds optional per-event system-prompt composition. When
the composition root supplies a :class:`PromptComposer` +
``capability_id`` (and optionally a ``scope_resolver`` callable), each
``propose()`` call re-composes the system message so operator-memory
entries can rotate in (via scope resolution) and canary tokens are
re-drawn per event. Falls back to the static ``config.system_prompt``
when a composer is not wired - existing tests and startup composition
paths remain valid.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.usage import TokenUsage
from fdai.core.operator_memory import OperatorScope
from fdai.core.prompts.composer import PromptComposer
from fdai.core.prompts.types import PromptMode, PromptReplayManifest
from fdai.core.quality_gate.gate import CrossCheckProposal, QualityCandidate
from fdai.core.tools import ToolExecutor, ToolRegistry
from fdai.delivery.azure.llm.gateway_evidence import record_gateway_route_evidence
from fdai.delivery.azure.llm.latency_routed_cross_check import ModelHealthTransitionSink
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity

# OpenAI function names accept ``[A-Za-z0-9_-]{1,64}`` only, so tool ids
# with dots (our catalog convention) need a lossless wire encoding. The
# model receives ``rule_query``; the adapter maps it back to
# ``rule.query`` via the id lookup built at construction so an attacker
# cannot inject an alternate id by guessing the underscored form.
_DOT_ENCODING: Final[str] = "_"


ScopeResolver = Callable[[QualityCandidate], OperatorScope | None]
"""Resolve an :class:`OperatorScope` from one :class:`QualityCandidate`.

The upstream repo stays CSP-neutral; the actual parsing of an ARM
resource id (or an equivalent identifier on another cloud) lives in a
fork's composition root. Return ``None`` when no scope can be resolved
- the composer then omits the operator-memory layer for that call.
"""


@dataclass(frozen=True, slots=True)
class AzureOpenAICrossCheckModelConfig:
    """Endpoint + deployment binding for one cross-check capability.

    ``system_prompt`` is a required field as of Wave 2 of the
    evolving-system-prompt design (``docs/roadmap/decisioning/prompt-composition.md``).
    Composition roots MUST supply the text produced by
    :class:`~fdai.core.prompts.PromptComposer` so the prompt lives
    in catalog-as-code, never in a code literal.

    ``max_tool_iterations`` bounds the multi-turn tool-calling loop.
    Any run that reaches this ceiling aborts to HIL rather than
    continuing to burn tokens; ``0`` disables tool calls entirely even
    if the composition root injected an executor.
    """

    endpoint: str
    deployment: str
    system_prompt: str
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 30.0
    max_tool_iterations: int = 3
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedSystemPrompt:
    text: str
    replay_manifest: PromptReplayManifest | None


class AzureOpenAICrossCheckModel:
    """Cross-check model backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAICrossCheckModelConfig,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        prompt_composer: PromptComposer | None = None,
        capability_id: str | None = None,
        scope_resolver: ScopeResolver | None = None,
        metering: MeteringEmitter | None = None,
        gateway_route_sink: ModelHealthTransitionSink | None = None,
    ) -> None:
        target = ModelRequestTarget(
            endpoint=config.endpoint,
            deployment=config.deployment,
            api_style=config.api_style,
            api_version=config.api_version,
            auth_audience=config.auth_audience,
            route_kind=config.route_kind,
            binding_id=config.binding_id,
        )
        if not config.system_prompt:
            raise ValueError(
                "system_prompt MUST NOT be empty - compose it via "
                "fdai.core.prompts.PromptComposer at the composition root"
            )
        if config.max_tokens < 1:
            raise ValueError("max_tokens MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not 0.0 <= config.temperature <= 2.0:
            raise ValueError("temperature MUST be in [0.0, 2.0]")
        if config.max_tool_iterations < 0:
            raise ValueError("max_tool_iterations MUST be >= 0")
        if (tool_registry is None) != (tool_executor is None):
            raise ValueError(
                "tool_registry and tool_executor MUST be provided together (both, or neither)"
            )
        # Wave 3 step C-2: ``prompt_composer`` and ``capability_id`` are
        # a matched pair. Either both are wired (per-event composition
        # active) or neither (fallback to ``config.system_prompt``).
        # ``scope_resolver`` MAY be wired only when the composer is
        # active - it has nothing to feed otherwise.
        if (prompt_composer is None) != (capability_id is None):
            raise ValueError(
                "prompt_composer and capability_id MUST be provided together (both, or neither)"
            )
        if capability_id is not None and not capability_id.strip():
            raise ValueError("capability_id MUST NOT be empty when provided")
        if scope_resolver is not None and prompt_composer is None:
            raise ValueError(
                "scope_resolver requires prompt_composer - the resolver "
                "output has no consumer without a composer wired"
            )

        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAICrossCheckModelConfig] = config
        self._tool_executor: Final[ToolExecutor | None] = tool_executor
        self._prompt_composer: Final[PromptComposer | None] = prompt_composer
        self._capability_id: Final[str | None] = capability_id
        self._scope_resolver: Final[ScopeResolver | None] = scope_resolver
        self._metering: Final[MeteringEmitter | None] = metering
        self._target: Final[ModelRequestTarget] = target
        self._gateway_route_sink = gateway_route_sink

        # Snapshot the enforce-mode tools at construction so the
        # advertised manifest is deterministic per model instance and
        # cannot drift under a running propose() call.
        tools_param: list[Mapping[str, Any]] | None
        name_to_id: dict[str, str] = {}
        if tool_registry is None or config.max_tool_iterations == 0:
            tools_param = None
        else:
            spec: list[Mapping[str, Any]] = []
            for artifact in tool_registry.artifacts():
                if artifact.default_mode is not PromptMode.ENFORCE:
                    continue
                function_name = _encode_function_name(artifact.id)
                name_to_id[function_name] = artifact.id
                spec.append(
                    {
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": artifact.description,
                            "parameters": dict(artifact.input_schema),
                        },
                    }
                )
            tools_param = spec if spec else None
        self._tools_param: Final[list[Mapping[str, Any]] | None] = tools_param
        self._name_to_id: Final[Mapping[str, str]] = name_to_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        proposal = await self.propose_with_evidence(candidate)
        return proposal.action_type, proposal.params

    async def propose_with_evidence(self, candidate: QualityCandidate) -> CrossCheckProposal:
        """Return a proposal plus prompt evidence scoped to this call."""

        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("chat/completions")
        resolved_prompt = await self._resolve_system_prompt(candidate)
        user_prompt = json.dumps(
            {
                "action_type": candidate.action_type,
                "target_resource_ref": candidate.target_resource_ref,
                "params": dict(candidate.params),
                "cited_rule_ids": list(candidate.cited_rule_ids),
            },
            sort_keys=True,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": resolved_prompt.text},
            {"role": "user", "content": user_prompt},
        ]

        # ``max_tool_iterations`` bounds the number of tool-dispatch
        # rounds; the final answer turn is always reachable after the
        # last permitted tool round, so we allow one extra loop cycle.
        #
        # Metering is emitted in ``finally`` so the tokens spent are
        # recorded on EVERY exit path - success, a tool-loop overflow, a
        # provider error, or a malformed final answer that routes to HIL.
        # Skipping metering on the failure paths would under-report real
        # spend (H7). ``emit_safe`` never raises, so the finally cannot
        # mask the original exception.
        total_usage = TokenUsage.zero()
        try:
            for iteration in range(self._config.max_tool_iterations + 1):
                body: dict[str, Any] = {
                    "messages": messages,
                    "temperature": self._config.temperature,
                    "max_tokens": self._config.max_tokens,
                    "response_format": {"type": "json_object"},
                }
                if self._tools_param is not None:
                    body["tools"] = self._tools_param
                    body["tool_choice"] = "auto"
                if request.model_body_field is not None:
                    body["model"] = request.model_body_field
                response = await self._http.post(
                    request.url,
                    params=request.params,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=self._config.timeout_seconds,
                )
                response.raise_for_status()
                await record_gateway_route_evidence(
                    response=response,
                    target=self._target,
                    model_role=self._capability_id or "t2.reasoner",
                    sink=self._gateway_route_sink,
                )
                envelope = response.json()
                call_usage = extract_usage(envelope)
                if call_usage is not None:
                    total_usage = total_usage + call_usage
                message = _extract_message(envelope)

                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    if iteration >= self._config.max_tool_iterations:
                        raise RuntimeError(
                            "cross-check model exceeded max_tool_iterations="
                            f"{self._config.max_tool_iterations}"
                        )
                    if self._tool_executor is None:
                        raise RuntimeError(
                            "cross-check model returned tool_calls but no ToolExecutor is wired"
                        )
                    # Preserve the assistant turn so the API sees the tool
                    # ids that the tool messages below refer to.
                    messages.append({"role": "assistant", "tool_calls": tool_calls})
                    for call in tool_calls:
                        tool_message = await self._dispatch_tool_call(call)
                        messages.append(tool_message)
                    continue

                content = message.get("content")
                action_type, params = _parse_final_answer(content)
                return CrossCheckProposal(
                    action_type=action_type,
                    params=params,
                    prompt_replay_manifest=resolved_prompt.replay_manifest,
                )

            # The loop always either returns or raises inside the body;
            # we never fall through, but mypy needs the explicit sentinel.
            raise RuntimeError("cross-check loop terminated without a final answer")
        finally:
            if self._metering is not None:
                await self._metering.emit_safe(total_usage)

    async def _resolve_system_prompt(self, candidate: QualityCandidate) -> _ResolvedSystemPrompt:
        """Return the system message for one ``propose()`` call.

        When a :class:`PromptComposer` is wired (Wave 3 step C-2), the
        prompt is re-composed per event so operator-memory entries
        rotate in (via ``scope_resolver``) and canary tokens are drawn
        fresh. Otherwise fall back to the static
        ``config.system_prompt`` snapshot taken at construction time.

        Any composer failure is wrapped as a :class:`RuntimeError` with
        the capability id so the quality gate routes the run to HIL
        rather than silently degrading to the fallback text.
        """

        composer = self._prompt_composer
        capability_id = self._capability_id
        if composer is None or capability_id is None:
            return _ResolvedSystemPrompt(text=self._config.system_prompt, replay_manifest=None)
        scope: OperatorScope | None = None
        if self._scope_resolver is not None:
            scope = self._scope_resolver(candidate)
        try:
            composed = await composer.compose(capability_id=capability_id, scope=scope)
        except Exception as exc:
            raise RuntimeError(
                f"prompt composition failed for capability_id={capability_id!r}: {exc}"
            ) from exc
        return _ResolvedSystemPrompt(
            text=composed.system_text,
            replay_manifest=composed.replay_manifest(),
        )

    async def _dispatch_tool_call(self, call: Mapping[str, Any]) -> dict[str, Any]:
        """Validate one tool_call, dispatch it, and format the tool message."""

        if not isinstance(call, Mapping):
            raise RuntimeError(f"tool_call MUST be an object, got {type(call).__name__}")
        function = call.get("function")
        if not isinstance(function, Mapping):
            raise RuntimeError("tool_call.function MUST be an object")
        function_name = function.get("name")
        if not isinstance(function_name, str) or not function_name:
            raise RuntimeError("tool_call.function.name MUST be a non-empty string")
        if function_name not in self._name_to_id:
            raise RuntimeError(f"cross-check model called unknown tool function {function_name!r}")
        tool_id = self._name_to_id[function_name]
        raw_arguments = function.get("arguments")
        arguments: Mapping[str, Any]
        if raw_arguments is None:
            arguments = {}
        elif isinstance(raw_arguments, str):
            try:
                parsed_args = json.loads(raw_arguments) if raw_arguments else {}
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"tool_call {function_name!r} carried non-JSON arguments: {raw_arguments!r}"
                ) from exc
            if not isinstance(parsed_args, dict):
                raise RuntimeError(
                    f"tool_call {function_name!r} arguments MUST decode to an "
                    f"object, got {type(parsed_args).__name__}"
                )
            arguments = parsed_args
        elif isinstance(raw_arguments, Mapping):
            arguments = raw_arguments
        else:
            raise RuntimeError(
                f"tool_call {function_name!r} arguments have unsupported type "
                f"{type(raw_arguments).__name__}"
            )
        # narrowed by the earlier ``tool_registry is not None`` guard in the
        # caller; a defensive raise here would be unreachable so we cast
        # for the type checker without asserting at runtime.
        executor = self._tool_executor
        if executor is None:  # pragma: no cover - unreachable
            raise RuntimeError("tool executor unexpectedly None inside dispatch loop")
        result = await executor.dispatch(tool_id=tool_id, arguments=arguments)
        return {
            "role": "tool",
            "tool_call_id": str(call.get("id") or function_name),
            "content": result.wrapped_text,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_function_name(tool_id: str) -> str:
    """Encode a catalog tool id for the OpenAI ``function.name`` slot.

    Dots become underscores; the reverse lookup relies on the
    per-instance map built at construction time, not on a string
    round-trip, so an attacker cannot smuggle a different id by
    guessing the underscored form.
    """

    return tool_id.replace(".", _DOT_ENCODING)


def _extract_message(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        message = envelope["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Azure OpenAI chat response missing choices[0].message: {envelope!r}"
        ) from exc
    if not isinstance(message, Mapping):
        raise RuntimeError(
            f"Azure OpenAI chat response message MUST be an object, got {type(message).__name__}"
        )
    return message


def _parse_final_answer(content: object) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(content, str) or not content:
        raise RuntimeError("cross-check final message MUST carry a JSON string content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cross-check model returned non-JSON content: {content!r}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"cross-check model MUST return a JSON object, got {type(parsed).__name__}"
        )
    action_type = parsed.get("action_type")
    params = parsed.get("params", {})
    if not isinstance(action_type, str) or not action_type:
        raise RuntimeError("cross-check response MUST carry a non-empty 'action_type' string")
    if not isinstance(params, dict):
        raise RuntimeError("cross-check response 'params' MUST be an object")
    return action_type, params


__all__ = [
    "AzureOpenAICrossCheckModel",
    "AzureOpenAICrossCheckModelConfig",
    "ScopeResolver",
]
