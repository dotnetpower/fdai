"""Azure-hosted semantic evaluator for completed conversation turns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

import httpx

from fdai.core.conversation_assurance import (
    AssuranceCriterion,
    CriterionScore,
    DebateContext,
    EvaluatorOutput,
    TurnAssessmentInput,
)
from fdai.core.metering import MeteringEmitter, TokenUsage
from fdai.core.metering.pricing import PricingTable
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_FORWARD_CHARS = 16_384


@dataclass(frozen=True, slots=True)
class AzureConversationAssuranceEvaluatorConfig:
    endpoint: str
    deployment: str
    model_identity: str
    model_family: str
    system_prompt: str
    api_version: str = "2024-06-01"
    max_tokens: int = 1_024
    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None

    def __post_init__(self) -> None:
        if not self.model_identity.strip() or not self.model_family.strip():
            raise ValueError("assurance model identity and family MUST be non-empty")
        if not self.system_prompt.strip():
            raise ValueError("assurance system_prompt MUST be non-empty")
        if not 256 <= self.max_tokens <= 4_096:
            raise ValueError("assurance max_tokens MUST be in [256, 4096]")
        if self.timeout_seconds <= 0.0:
            raise ValueError("assurance timeout_seconds MUST be positive")


class AzureConversationAssuranceEvaluator:
    """Call one configured evaluator; reduction and authority stay in core."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureConversationAssuranceEvaluatorConfig,
        metering: MeteringEmitter | None = None,
        pricing: PricingTable | None = None,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
        self._metering = metering
        self._pricing = pricing
        self._target = ModelRequestTarget(
            endpoint=config.endpoint,
            deployment=config.deployment,
            api_style=config.api_style,
            api_version=config.api_version,
            auth_audience=config.auth_audience,
            route_kind=config.route_kind,
            binding_id=config.binding_id,
        )

    @property
    def model_identity(self) -> str:
        return self._config.model_identity

    @property
    def model_family(self) -> str:
        return self._config.model_family

    @property
    def prospective_cost_microusd(self) -> int:
        if self._pricing is None:
            return 50_000
        price = self._pricing.pricing_for(self.model_family)
        if price is None:
            return 50_000
        usage = TokenUsage(
            prompt_tokens=_MAX_FORWARD_CHARS // 4,
            completion_tokens=self._config.max_tokens,
        )
        return _cost_microusd(price.cost_of(usage))

    async def evaluate(
        self,
        turn: TurnAssessmentInput,
        *,
        debate: DebateContext | None = None,
    ) -> EvaluatorOutput:
        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("chat/completions")
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": _evaluation_prompt(turn, debate=debate)},
            ],
            "temperature": 0.0,
            "max_tokens": self._config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        usage: TokenUsage | None = None
        try:
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
            extracted = extract_usage(envelope)
            if extracted is not None:
                usage = extracted
            scores = _parse_scores(_message_content(envelope))
            measured_usage = usage or TokenUsage.zero()
            return EvaluatorOutput(
                model_identity=self.model_identity,
                model_family=self.model_family,
                scores=scores,
                prompt_tokens=measured_usage.prompt_tokens,
                completion_tokens=measured_usage.completion_tokens,
                cost_microusd=self._actual_cost_microusd(measured_usage),
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"conversation assurance request failed: {type(exc).__name__}"
            ) from exc
        finally:
            if self._metering is not None and usage is not None:
                await self._metering.emit_safe(usage)

    def _actual_cost_microusd(self, usage: TokenUsage) -> int:
        if self._pricing is None:
            return 0
        cost = self._pricing.cost_of(model_key=self.model_family, usage=usage)
        return _cost_microusd(cost) if cost is not None else 0


def _evaluation_prompt(
    turn: TurnAssessmentInput,
    *,
    debate: DebateContext | None,
) -> str:
    payload: dict[str, object] = {
        "turn_data_trusted": False,
        "question": turn.question[:_MAX_FORWARD_CHARS],
        "answer": turn.answer[:_MAX_FORWARD_CHARS],
        "locale": turn.locale,
        "verification": {
            "status": turn.verification_status,
            "authority": turn.verification_authority,
            "checks_completed": turn.checks_completed,
            "checks_total": turn.checks_total,
            "failed_claim_ids": list(turn.failed_claim_ids),
        },
        "allowed_evidence_refs": list(turn.evidence_refs),
    }
    if debate is not None:
        payload["tie_break"] = {
            "disputed_criteria": [item.value for item in debate.disputed_criteria],
            "first": _output_for_prompt(debate.first),
            "second": _output_for_prompt(debate.second),
        }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _output_for_prompt(output: EvaluatorOutput) -> dict[str, object]:
    return {
        "model_family": output.model_family,
        "scores": [
            {
                "criterion": item.criterion.value,
                "score": item.score,
                "rationale": item.rationale,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in output.scores
        ],
    }


def _message_content(envelope: object) -> str:
    if not isinstance(envelope, Mapping):
        raise RuntimeError("conversation assurance response MUST be a JSON object")
    try:
        choices = envelope["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("conversation assurance response is missing message content") from exc
    if not isinstance(content, str) or not content:
        raise RuntimeError("conversation assurance message content MUST be non-empty")
    return content


def _parse_scores(content: str) -> tuple[CriterionScore, ...]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("conversation assurance model returned non-JSON content") from exc
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("scores"), list):
        raise RuntimeError("conversation assurance response MUST contain a scores array")
    scores: list[CriterionScore] = []
    for raw in parsed["scores"]:
        if not isinstance(raw, Mapping):
            raise RuntimeError("conversation assurance score MUST be an object")
        criterion_raw = raw.get("criterion")
        if not isinstance(criterion_raw, str):
            raise RuntimeError("conversation assurance criterion MUST be a string")
        try:
            criterion = AssuranceCriterion(criterion_raw)
        except ValueError as exc:
            raise RuntimeError("conversation assurance criterion is unsupported") from exc
        score = raw.get("score")
        if isinstance(score, bool) or not isinstance(score, int):
            raise RuntimeError("conversation assurance score MUST be an integer")
        if not 0 <= score <= 4:
            raise RuntimeError("conversation assurance score MUST be in [0, 4]")
        rationale = raw.get("rationale")
        if not isinstance(rationale, str):
            raise RuntimeError("conversation assurance rationale MUST be a string")
        evidence_raw = raw.get("evidence_refs")
        if not isinstance(evidence_raw, list) or not all(
            isinstance(item, str) for item in evidence_raw
        ):
            raise RuntimeError("conversation assurance evidence_refs MUST be a string array")
        scores.append(
            CriterionScore(
                criterion=criterion,
                score=score,
                rationale=rationale,
                evidence_refs=tuple(evidence_raw),
            )
        )
    return tuple(scores)


def _cost_microusd(cost: Decimal) -> int:
    return int((cost * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))


__all__ = [
    "AzureConversationAssuranceEvaluator",
    "AzureConversationAssuranceEvaluatorConfig",
]
