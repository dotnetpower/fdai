"""AzureOpenAIJudgeModel - httpx-based Judge client (Wave 4.5 beta).

Implements :class:`~fdai.core.quality_gate.judge.JudgeModel` by
calling Azure OpenAI ``chat/completions`` with structured JSON output.
The response MUST parse into
:class:`~fdai.core.quality_gate.judge.JudgeOutput`; anything else
raises so the future :class:`DebateOrchestrator` cannot silently
accept a malformed decision - the same "verifier is the authority"
invariant the cross-check and critic adapters honor.

Bound to the ``t1.judge`` capability - the Judge is intentionally a
smaller / cheaper model per
``docs/roadmap/decisioning/prompt-composition.md § Debate orchestrator``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.core.quality_gate.critic import CriticOutput
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.judge import (
    JudgeDecision,
    JudgeOutput,
)
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class AzureOpenAIJudgeModelConfig:
    """Endpoint + deployment binding for the Judge capability.

    ``system_prompt`` is REQUIRED - upstream composes it from
    ``rule-catalog/prompts/base/t2-judge.v1.yaml`` via
    :class:`~fdai.core.prompts.PromptComposer`.
    """

    endpoint: str
    deployment: str
    system_prompt: str
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None


class AzureOpenAIJudgeModel:
    """Judge role backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIJudgeModelConfig,
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

        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAIJudgeModelConfig] = config
        self._target: Final[ModelRequestTarget] = target

    async def judge(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
        critic_output: CriticOutput,
    ) -> JudgeOutput:
        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("chat/completions")
        proposer_action_type, proposer_params = proposer_output
        user_prompt = json.dumps(
            {
                "candidate": {
                    "action_type": candidate.action_type,
                    "target_resource_ref": candidate.target_resource_ref,
                    "params": dict(candidate.params),
                    "cited_rule_ids": list(candidate.cited_rule_ids),
                },
                "proposer_output": {
                    "action_type": proposer_action_type,
                    "params": dict(proposer_params),
                },
                "critic_output": {
                    "stance": critic_output.stance.value,
                    "objections": [
                        {
                            "severity": obj.severity.value,
                            "cited_rule_id": obj.cited_rule_id,
                            "description": obj.description,
                            "alt_action_type": obj.alt_action_type,
                        }
                        for obj in critic_output.objections
                    ],
                    "citations": list(critic_output.citations),
                },
            },
            sort_keys=True,
        )
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "response_format": {"type": "json_object"},
        }
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
        envelope = response.json()
        message = _extract_message(envelope)
        return _parse_judge_output(message.get("content"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _parse_judge_output(content: object) -> JudgeOutput:
    """Parse the JSON body into a validated :class:`JudgeOutput`.

    Every parse failure raises :class:`RuntimeError` so the future
    debate orchestrator routes the run to HIL rather than silently
    accepting a malformed judgement. ``JudgeOutput.__post_init__``
    also raises on blank justification.
    """

    if not isinstance(content, str) or not content:
        raise RuntimeError("judge final message MUST carry a JSON string content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"judge model returned non-JSON content: {content!r}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"judge model MUST return a JSON object, got {type(parsed).__name__}")

    decision_raw = parsed.get("decision")
    if not isinstance(decision_raw, str) or not decision_raw:
        raise RuntimeError("judge response MUST carry a non-empty 'decision' string")
    try:
        decision = JudgeDecision(decision_raw)
    except ValueError as exc:
        allowed = [d.value for d in JudgeDecision]
        raise RuntimeError(
            f"judge 'decision' MUST be one of {allowed!r}, got {decision_raw!r}"
        ) from exc

    justification = parsed.get("justification")
    if not isinstance(justification, str):
        raise RuntimeError("judge 'justification' MUST be a string")

    retry_directive_raw = parsed.get("retry_directive")
    retry_directive: str | None
    if retry_directive_raw is None:
        retry_directive = None
    elif isinstance(retry_directive_raw, str):
        retry_directive = retry_directive_raw or None
    else:
        raise RuntimeError(
            f"judge 'retry_directive' MUST be a string or absent, got "
            f"{type(retry_directive_raw).__name__}"
        )

    citations_raw = parsed.get("citations", [])
    if not isinstance(citations_raw, list):
        raise RuntimeError(
            f"judge 'citations' MUST be an array, got {type(citations_raw).__name__}"
        )
    for i, cit in enumerate(citations_raw):
        if not isinstance(cit, str) or not cit.strip():
            raise RuntimeError(f"judge citations[{i}] MUST be a non-empty string, got {cit!r}")
    citations = tuple(citations_raw)

    # ``JudgeOutput.__post_init__`` enforces non-blank justification.
    return JudgeOutput(
        decision=decision,
        justification=justification,
        retry_directive=retry_directive,
        citations=citations,
    )


__all__ = [
    "AzureOpenAIJudgeModel",
    "AzureOpenAIJudgeModelConfig",
]
