"""AzureOpenAICriticModel - httpx-based T2 Critic client (Wave 4 beta-1).

Implements :class:`~aiopspilot.core.quality_gate.critic.CriticModel` by
calling Azure OpenAI ``chat/completions`` with structured JSON output.
The response MUST parse into the shape
:class:`~aiopspilot.core.quality_gate.critic.CriticOutput` expects
(``stance``, ``objections``, ``citations``); anything else raises so
the caller cannot silently accept a malformed critique - the same
"verifier is the authority" invariant that governs the cross-check
adapter.

Scope of this slice
-------------------
- Static ``system_prompt`` from :class:`AzureOpenAICriticModelConfig`.
  Per-event composition via :class:`PromptComposer` (mirroring the
  cross-check adapter's Wave 3 step C-2 wire) is a follow-up slice;
  the shipped catalog seed at ``rule-catalog/prompts/base/t2-critic.v1.yaml``
  is still ``default_mode: shadow`` so the model is not yet plugged
  into any live QualityGate flow.
- No tool-calling loop. The Critic reviews the Proposer's candidate;
  it does not itself dispatch tools (per
  ``docs/roadmap/prompt-composition.md § Debate orchestrator``).
- Composition-root wiring lands in Wave 4 beta-2 alongside a
  ``t2.critic`` capability entry in ``rule-catalog/llm-registry.yaml``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from aiopspilot.core.quality_gate.critic import (
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
)
from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_COGNITIVE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class AzureOpenAICriticModelConfig:
    """Endpoint + deployment binding for the Critic capability.

    ``system_prompt`` is REQUIRED - upstream composes it from
    ``rule-catalog/prompts/base/t2-critic.v1.yaml`` via
    :class:`~aiopspilot.core.prompts.PromptComposer`. Never populate
    with an inline code literal; that would re-open the drift path
    Wave 2 closed for the cross-check adapter.
    """

    endpoint: str
    deployment: str
    system_prompt: str
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 30.0


class AzureOpenAICriticModel:
    """Critic role backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAICriticModelConfig,
    ) -> None:
        if not config.endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint MUST be an absolute https URL")
        if not config.deployment:
            raise ValueError("deployment MUST NOT be empty")
        if not config.system_prompt:
            raise ValueError(
                "system_prompt MUST NOT be empty - compose it via "
                "aiopspilot.core.prompts.PromptComposer at the composition root"
            )
        if config.max_tokens < 1:
            raise ValueError("max_tokens MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not 0.0 <= config.temperature <= 2.0:
            raise ValueError("temperature MUST be in [0.0, 2.0]")

        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAICriticModelConfig] = config

    async def critique(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
    ) -> CriticOutput:
        token = await self._identity.get_token(_COGNITIVE_SCOPE)
        url = (
            self._config.endpoint.rstrip("/")
            + "/openai/deployments/"
            + self._config.deployment
            + "/chat/completions"
        )
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
        response = await self._http.post(
            url,
            params={"api-version": self._config.api_version},
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
        return _parse_critic_output(message.get("content"))


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


def _parse_critic_output(content: object) -> CriticOutput:
    """Parse the JSON body into a validated :class:`CriticOutput`.

    Every parse failure raises :class:`RuntimeError` with a descriptive
    message so the caller (the future debate orchestrator) can route
    the run to HIL rather than silently accepting a malformed critique.
    ``CriticObjection.__post_init__`` also raises on blank citations /
    descriptions, so those defects are caught at the type-boundary
    even if this parser missed them.
    """

    if not isinstance(content, str) or not content:
        raise RuntimeError("critic final message MUST carry a JSON string content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"critic model returned non-JSON content: {content!r}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"critic model MUST return a JSON object, got {type(parsed).__name__}")

    stance_raw = parsed.get("stance")
    if not isinstance(stance_raw, str) or not stance_raw:
        raise RuntimeError("critic response MUST carry a non-empty 'stance' string")
    try:
        stance = CriticStance(stance_raw)
    except ValueError as exc:
        allowed = [s.value for s in CriticStance]
        raise RuntimeError(
            f"critic 'stance' MUST be one of {allowed!r}, got {stance_raw!r}"
        ) from exc

    objections_raw = parsed.get("objections", [])
    if not isinstance(objections_raw, list):
        raise RuntimeError(
            f"critic 'objections' MUST be an array, got {type(objections_raw).__name__}"
        )
    objections = tuple(_parse_objection(obj, index=i) for i, obj in enumerate(objections_raw))

    citations_raw = parsed.get("citations", [])
    if not isinstance(citations_raw, list):
        raise RuntimeError(
            f"critic 'citations' MUST be an array, got {type(citations_raw).__name__}"
        )
    for i, cit in enumerate(citations_raw):
        if not isinstance(cit, str) or not cit.strip():
            raise RuntimeError(f"critic citations[{i}] MUST be a non-empty string, got {cit!r}")
    citations = tuple(citations_raw)

    return CriticOutput(stance=stance, objections=objections, citations=citations)


def _parse_objection(raw: object, *, index: int) -> CriticObjection:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            f"critic objections[{index}] MUST be an object, got {type(raw).__name__}"
        )
    severity_raw = raw.get("severity")
    if not isinstance(severity_raw, str) or not severity_raw:
        raise RuntimeError(f"critic objections[{index}].severity MUST be a non-empty string")
    try:
        severity = CriticSeverity(severity_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"critic objections[{index}].severity MUST be one of "
            f"{[s.value for s in CriticSeverity]!r}, got {severity_raw!r}"
        ) from exc
    cited_rule_id = raw.get("cited_rule_id")
    description = raw.get("description")
    if not isinstance(cited_rule_id, str):
        raise RuntimeError(f"critic objections[{index}].cited_rule_id MUST be a string")
    if not isinstance(description, str):
        raise RuntimeError(f"critic objections[{index}].description MUST be a string")
    alt_action_raw = raw.get("alt_action_type")
    alt_action: str | None
    if alt_action_raw is None:
        alt_action = None
    elif isinstance(alt_action_raw, str):
        alt_action = alt_action_raw or None
    else:
        raise RuntimeError(f"critic objections[{index}].alt_action_type MUST be a string or absent")
    # ``CriticObjection.__post_init__`` performs the blank-strip check.
    return CriticObjection(
        severity=severity,
        cited_rule_id=cited_rule_id,
        description=description,
        alt_action_type=alt_action,
    )


__all__ = [
    "AzureOpenAICriticModel",
    "AzureOpenAICriticModelConfig",
]
