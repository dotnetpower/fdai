"""Single-call Azure OpenAI worker planning with pre-dispatch token and price ceilings.

The provider prepares only isolated input, never inherits a Pantheon conversation, and emits no
tool or action requests. Token usage is authoritative response data; cost is configured-rate USD
accounting, not provider invoice evidence. Missing usage retains the caller's unresolved reserve.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

import httpx

from fdai.core.conversation.answer_planning import AnswerContribution, GroundedFact
from fdai.core.metering import TokenUsage
from fdai.core.metering.pricing import ModelPricing
from fdai.core.task_worker.models import TaskWorkerUsage
from fdai.core.task_worker.planning_executor import (
    PreparedTaskWorkerPlanning,
    TaskWorkerPlanningError,
    TaskWorkerPlanningResponse,
)
from fdai.core.task_worker.tools import TaskWorkerPlanningBudgetError
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE, ModelRequestTarget
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts", "caveats", "evidence_refs", "confidence"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "evidence_ref"],
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ref": {"type": "string"},
                },
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
}


@dataclass(frozen=True, slots=True)
class AzureTaskWorkerPlanningConfig:
    """Bind a reviewed direct OpenAI target and immutable USD rates, without selecting one."""

    target: ModelRequestTarget
    model_family: str
    pricing: ModelPricing
    max_output_tokens: int = 1_024
    timeout_seconds: float = 30.0
    max_response_bytes: int = 131_072

    def __post_init__(self) -> None:
        if (
            self.target.api_style is not ModelApiStyle.AZURE_OPENAI
            or self.target.route_kind is not ModelRouteKind.DIRECT
            or self.target.auth_audience != COGNITIVE_SERVICES_SCOPE
            or not self.model_family.startswith(("gpt-4", "gpt-5", "o1", "o3", "o4"))
        ):
            raise ValueError("worker planning requires a supported direct Azure OpenAI target")
        if self.pricing.currency != "USD":
            raise ValueError("worker planning requires explicit USD pricing")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 4_096:
            raise ValueError("worker output token limit MUST be in [1, 4096]")
        if not 0 < self.timeout_seconds <= 300:
            raise ValueError("worker provider timeout MUST be in (0, 300]")
        if (
            type(self.max_response_bytes) is not int
            or not 1_024 <= self.max_response_bytes <= 131_072
        ):
            raise ValueError("worker provider response limit MUST be in [1024, 131072]")


class AzureTaskWorkerPlanningProvider:
    """Prepare and execute exactly one bounded, untrusted answer contribution; never retry."""

    def __init__(
        self,
        *,
        config: AzureTaskWorkerPlanningConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    def prepare_contribution(
        self, *, agent: str, prompt: str, max_tokens: int, max_cost_microusd: int
    ) -> PreparedTaskWorkerPlanning:
        """Fit one request's byte-token upper bound and maximum output charge before any I/O.

        Supported OpenAI tokenizers encode UTF-8 bytes, not more than one ordinary token per byte.
        Counting the complete JSON (including schema) plus 256 framing tokens is deliberately
        conservative. Returned usage is checked against that bound, never estimated from prose.
        """
        if agent != "Bragi" or not prompt or len(prompt.encode("utf-8")) > 131_072:
            raise ValueError("worker planning requires bounded Bragi presentation input")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 32_768:
            raise ValueError("worker token budget MUST be in [1, 32768]")
        if type(max_cost_microusd) is not int or not 0 <= max_cost_microusd <= 10_000_000:
            raise ValueError("worker cost budget MUST be in [0, 10000000]")
        body = self._body(prompt, self._config.max_output_tokens)
        input_bound = len(_json_bytes(body)) + 256
        output_limit = min(self._config.max_output_tokens, max_tokens - input_bound)
        if output_limit < 1:
            raise TaskWorkerPlanningBudgetError("worker input cannot fit the token ceiling")
        maximum_cost = self._cost(TokenUsage(input_bound, output_limit))
        if maximum_cost > max_cost_microusd:
            raise TaskWorkerPlanningBudgetError("worker request cannot fit the cost ceiling")
        target = self._config.target
        binding = _json_bytes(
            {
                "target": target.operation("chat/completions").url,
                "api_version": target.api_version,
                "audience": target.auth_audience,
                "family": self._config.model_family,
                "input_rate": str(self._config.pricing.input_per_1k),
                "output_rate": str(self._config.pricing.output_per_1k),
                "body": self._body(prompt, output_limit),
            }
        )
        return PreparedTaskWorkerPlanning(
            agent=agent,
            prompt=prompt,
            max_tokens=max_tokens,
            max_cost_microusd=max_cost_microusd,
            input_token_upper_bound=input_bound,
            output_token_limit=output_limit,
            cost_upper_bound_microusd=maximum_cost,
            binding_digest=hashlib.sha256(binding).hexdigest(),
        )

    async def contribute_bounded(
        self, *, agent: str, prompt: str, max_tokens: int, max_cost_microusd: int
    ) -> TaskWorkerPlanningResponse:
        """Preserve the original seam; durable workers call the prepared seam instead."""
        return await self.contribute_prepared(
            self.prepare_contribution(
                agent=agent,
                prompt=prompt,
                max_tokens=max_tokens,
                max_cost_microusd=max_cost_microusd,
            )
        )

    async def contribute_prepared(
        self, prepared: PreparedTaskWorkerPlanning
    ) -> TaskWorkerPlanningResponse:
        """Revalidate preparation and make one request; preserve known usage on parse failure."""
        expected = self.prepare_contribution(
            agent=prepared.agent,
            prompt=prepared.prompt,
            max_tokens=prepared.max_tokens,
            max_cost_microusd=prepared.max_cost_microusd,
        )
        if prepared != expected:
            raise ValueError("worker prepared request no longer matches its binding")
        request = self._config.target.operation("chat/completions")
        token = await self._identity.get_token(self._config.target.auth_audience)
        measured: TaskWorkerUsage | None = None
        try:
            async with self._http.stream(
                "POST",
                request.url,
                params=request.params,
                headers={"Authorization": f"Bearer {token.token}"},
                json=self._body(prepared.prompt, prepared.output_token_limit),
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise TaskWorkerPlanningError("worker provider request was not accepted")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(payload) + len(chunk) > self._config.max_response_bytes:
                        raise TaskWorkerPlanningError("worker provider response exceeded its bound")
                    payload.extend(chunk)
            envelope = json.loads(payload, object_pairs_hook=_unique_object)
            usage = _measured_usage(envelope)
            measured = TaskWorkerUsage(tokens=usage.total_tokens, cost_microusd=self._cost(usage))
            if (
                usage.prompt_tokens > prepared.input_token_upper_bound
                or usage.completion_tokens > prepared.output_token_limit
            ):
                raise ValueError("provider usage exceeded its prepared bound")
            contribution = _contribution(envelope, agent=prepared.agent)
            return TaskWorkerPlanningResponse(
                contribution=contribution,
                tokens=measured.tokens,
                cost_microusd=measured.cost_microusd,
            )
        except TaskWorkerPlanningError:
            raise
        except (ValueError, TypeError, KeyError, IndexError, httpx.HTTPError) as error:
            raise TaskWorkerPlanningError(
                "worker provider response or transport is invalid", usage=measured
            ) from error

    def _cost(self, usage: TokenUsage) -> int:
        amount = self._config.pricing.cost_of(usage) * Decimal(1_000_000)
        return int(amount.to_integral_value(rounding=ROUND_CEILING))

    def _body(self, prompt: str, output_limit: int) -> dict[str, Any]:
        return {
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "worker_contribution", "strict": True, "schema": _SCHEMA},
            },
            **completion_body_params(
                self._config.model_family, temperature=0.0, max_tokens=output_limit
            ),
        }


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("worker provider JSON contains duplicate keys")
        result[name] = value
    return result


def _measured_usage(envelope: object) -> TokenUsage:
    if not isinstance(envelope, Mapping) or not isinstance(envelope.get("usage"), Mapping):
        raise ValueError("worker provider usage is unavailable")
    raw = envelope["usage"]
    values = [raw.get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("worker provider usage is malformed")
    prompt, completion, total = values
    if prompt + completion != total:
        raise ValueError("worker provider total usage is inconsistent")
    return TokenUsage(prompt_tokens=prompt, completion_tokens=completion)


def _contribution(envelope: Mapping[str, Any], *, agent: str) -> AnswerContribution:
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("worker provider requires exactly one response choice")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ValueError("worker provider message is invalid")
    if message.get("tool_calls") or message.get("function_call") or message.get("refusal"):
        raise ValueError("worker provider returned unsupported non-presentation output")
    raw = json.loads(message["content"], object_pairs_hook=_unique_object)
    if not isinstance(raw, dict) or set(raw) != {"facts", "caveats", "evidence_refs", "confidence"}:
        raise ValueError("worker contribution fields are invalid")
    if not isinstance(raw["facts"], list) or len(raw["facts"]) > 32:
        raise ValueError("worker fact list is invalid")
    facts = []
    for fact in raw["facts"]:
        if not isinstance(fact, dict) or set(fact) != {"claim", "evidence_ref"}:
            raise ValueError("worker fact fields are invalid")
        if not all(isinstance(value, str) for value in fact.values()):
            raise ValueError("worker fact values MUST be text")
        facts.append(GroundedFact(fact["claim"], fact["evidence_ref"]))
    for name in ("caveats", "evidence_refs"):
        if not isinstance(raw[name], list) or not all(
            isinstance(value, str) for value in raw[name]
        ):
            raise ValueError("worker contribution lists MUST contain text")
    confidence = raw["confidence"]
    if type(confidence) not in {int, float}:
        raise ValueError("worker confidence MUST be numeric")
    return AnswerContribution(
        agent=agent,
        facts=tuple(facts),
        caveats=tuple(raw["caveats"]),
        suggested_sections=(),
        evidence_refs=tuple(raw["evidence_refs"]),
        confidence=confidence,
    )
