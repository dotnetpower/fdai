"""AzureOpenAIRubricEvaluator - httpx-based T2 rubric judge client.

Implements :class:`~fdai.core.quality_gate.rubric.RubricEvaluator` by
calling Azure OpenAI ``chat/completions`` with structured JSON output.
The model scores a :class:`~fdai.core.quality_gate.gate.QualityCandidate`
against the fixed rubric criteria; the response MUST parse into the shape
:class:`~fdai.core.quality_gate.rubric.RubricOutput` expects
(``scores[].criterion`` / ``score`` / ``rationale`` /
``supporting_rule_ids``). Anything else raises so the caller fails
closed to HIL - the same "verifier is the authority" invariant that
governs the cross-check and critic adapters.

Threshold is CONFIGURATION, never model output
----------------------------------------------
The per-criterion pass threshold is injected from
:class:`AzureOpenAIRubricEvaluatorConfig`, not read from the model
response - a model must not set its own passing bar. The catalog prompt
(``rule-catalog/prompts/base/t2-rubric.v1.yaml``) explicitly instructs
the model NOT to emit a threshold or a verdict.

Mixed-model
-----------
The rubric judge MUST be a different publisher than
``t2.reasoner.primary`` (a model grading its own answer defeats the
independence assumption). That is enforced at config load in
``llm_resolver.py`` (``_enforce_mixed_model_invariant``); this adapter
only implements the transport.

Scope of this slice
-------------------
- Static ``system_prompt`` from the config (composed upstream from the
  catalog seed via :class:`~fdai.core.prompts.PromptComposer`). Per-event
  composition is a follow-up, mirroring the critic adapter.
- No tool-calling loop. The judge scores; it does not dispatch tools.
- The shipped catalog seed is ``default_mode: shadow`` so a wired
  evaluator runs judge-and-log until a fork meets the promotion gate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.usage import TokenUsage
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.rubric import RubricCriterion, RubricOutput, RubricScore
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.shared.providers.workload_identity import WorkloadIdentity

_COGNITIVE_SCOPE: Final[str] = "https://cognitiveservices.azure.com/.default"

_DEFAULT_CRITERIA: Final[tuple[str, ...]] = tuple(c.value for c in RubricCriterion)
_VALID_CRITERIA: Final[frozenset[str]] = frozenset(c.value for c in RubricCriterion)


@dataclass(frozen=True, slots=True)
class AzureOpenAIRubricEvaluatorConfig:
    """Endpoint + deployment binding for the rubric judge capability.

    ``system_prompt`` is REQUIRED - upstream composes it from
    ``rule-catalog/prompts/base/t2-rubric.v1.yaml`` via
    :class:`~fdai.core.prompts.PromptComposer`. Never populate with an
    inline code literal.

    ``default_threshold`` is the pass floor applied to every criterion
    the model scores; ``thresholds`` overrides it per criterion. Both
    are configuration - the model never sets its own bar.
    """

    endpoint: str
    deployment: str
    system_prompt: str
    default_threshold: float = 0.7
    thresholds: Mapping[str, float] = field(default_factory=dict)
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 30.0
    max_reasoning_trace_chars: int = 8000
    """Cap on the ``reasoning_trace`` length forwarded to the judge. An
    untrusted / buggy proposer could emit a huge trace that blows up the
    prompt token cost (and the prompt-injection surface); the adapter
    truncates beyond this and marks the cut so the judge scores the
    truncation as a coherence signal rather than paying for the tail."""


class AzureOpenAIRubricEvaluator:
    """Rubric judge backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIRubricEvaluatorConfig,
        metering: MeteringEmitter | None = None,
    ) -> None:
        if not config.endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint MUST be an absolute https URL")
        if not config.deployment:
            raise ValueError("deployment MUST NOT be empty")
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
        if not 0.0 <= config.default_threshold <= 1.0:
            raise ValueError("default_threshold MUST be in [0.0, 1.0]")
        if config.max_reasoning_trace_chars < 1:
            raise ValueError("max_reasoning_trace_chars MUST be >= 1")
        for name, value in config.thresholds.items():
            if name not in _VALID_CRITERIA:
                raise ValueError(
                    f"threshold key {name!r} is not a valid RubricCriterion "
                    f"(one of {sorted(_VALID_CRITERIA)}) - a typo would be "
                    "silently ignored otherwise"
                )
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"threshold for {name!r} MUST be in [0.0, 1.0], got {value}")

        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureOpenAIRubricEvaluatorConfig] = config
        self._metering: Final[MeteringEmitter | None] = metering

    def _threshold_for(self, criterion: str) -> float:
        return self._config.thresholds.get(criterion, self._config.default_threshold)

    def _clamp_trace(self, trace: str) -> str:
        cap = self._config.max_reasoning_trace_chars
        if len(trace) <= cap:
            return trace
        dropped = len(trace) - cap
        return f"{trace[:cap]}...[truncated {dropped} chars]"

    async def score(self, candidate: QualityCandidate) -> RubricOutput:
        token = await self._identity.get_token(_COGNITIVE_SCOPE)
        url = (
            self._config.endpoint.rstrip("/")
            + "/openai/deployments/"
            + self._config.deployment
            + "/chat/completions"
        )
        user_prompt = json.dumps(
            {
                "candidate": {
                    "action_type": candidate.action_type,
                    "target_resource_ref": candidate.target_resource_ref,
                    "params": dict(candidate.params),
                    "cited_rule_ids": list(candidate.cited_rule_ids),
                    "reasoning_trace": self._clamp_trace(candidate.reasoning_trace),
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
        # Metering is emitted in ``finally`` so spent tokens are recorded on
        # EVERY exit path - success, a provider error, or a malformed answer
        # that routes to HIL. ``emit_safe`` never raises, so the finally
        # cannot mask the original exception. Cost governance is a first-class
        # vertical; a judge call that is not metered under-reports T2 spend.
        total_usage = TokenUsage.zero()
        try:
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
            call_usage = extract_usage(envelope)
            if call_usage is not None:
                total_usage = total_usage + call_usage
            message = _extract_message(envelope)
            return self._parse_rubric_output(message.get("content"))
        finally:
            if self._metering is not None:
                await self._metering.emit_safe(total_usage)

    def _parse_rubric_output(self, content: object) -> RubricOutput:
        """Parse the JSON body into a validated :class:`RubricOutput`.

        Every parse failure raises :class:`RuntimeError` so the
        :class:`~fdai.core.quality_gate.gate.QualityGate` fails closed to
        HIL rather than accepting a malformed judgment. The per-criterion
        threshold is injected from config here (never read from the
        model). ``RubricScore.__post_init__`` also raises on an
        out-of-range score / blank rationale, catching defects at the
        type boundary.
        """
        if not isinstance(content, str) or not content:
            raise RuntimeError("rubric final message MUST carry a JSON string content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"rubric model returned non-JSON content: {content!r}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(
                f"rubric model MUST return a JSON object, got {type(parsed).__name__}"
            )
        raw_scores = parsed.get("scores")
        if not isinstance(raw_scores, list):
            raise RuntimeError("rubric response MUST carry a 'scores' array")

        scores: list[RubricScore] = []
        for entry in raw_scores:
            if not isinstance(entry, Mapping):
                raise RuntimeError(
                    f"rubric score entry MUST be an object, got {type(entry).__name__}"
                )
            criterion = entry.get("criterion")
            if not isinstance(criterion, str) or not criterion:
                raise RuntimeError("rubric score MUST carry a non-empty 'criterion' string")
            score_raw = entry.get("score")
            if not isinstance(score_raw, (int, float)) or isinstance(score_raw, bool):
                raise RuntimeError(f"rubric 'score' MUST be a number, got {score_raw!r}")
            rationale = entry.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise RuntimeError("rubric score MUST carry a non-empty 'rationale' string")
            supporting_raw = entry.get("supporting_rule_ids", [])
            if not isinstance(supporting_raw, list) or not all(
                isinstance(r, str) for r in supporting_raw
            ):
                raise RuntimeError("rubric 'supporting_rule_ids' MUST be an array of strings")
            scores.append(
                RubricScore(
                    criterion=criterion,
                    score=float(score_raw),
                    threshold=self._threshold_for(criterion),
                    rationale=rationale,
                    supporting_rule_ids=tuple(supporting_raw),
                )
            )
        return RubricOutput(scores=tuple(scores))


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


__all__ = [
    "AzureOpenAIRubricEvaluator",
    "AzureOpenAIRubricEvaluatorConfig",
]
