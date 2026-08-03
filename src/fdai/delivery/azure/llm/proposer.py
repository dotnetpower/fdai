"""Azure OpenAI adapter for bounded, catalog-grounded T2 proposals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.tiers.t2_reasoning import T2ProposalContext
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.gateway_evidence import record_gateway_route_evidence
from fdai.delivery.azure.llm.latency_routed_cross_check import ModelHealthTransitionSink
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity

_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {"authorization", "credential", "password", "secret", "token"}
)


@dataclass(frozen=True, slots=True)
class AzureOpenAIProposerConfig:
    endpoint: str
    deployment: str
    system_prompt: str
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    model_family: str | None = None
    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None


class AzureOpenAIProposer:
    """Create a candidate from an immutable, caller-bounded context."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIProposerConfig,
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
            raise ValueError("system_prompt MUST NOT be empty")
        if config.max_tokens < 1:
            raise ValueError("max_tokens MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not 0.0 <= config.temperature <= 2.0:
            raise ValueError("temperature MUST be in [0.0, 2.0]")
        self._identity = identity
        self._http = http_client
        self._config = config
        self._metering = metering
        self._target = target
        self._gateway_route_sink = gateway_route_sink

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        if not context.allowed_rules or not context.target_resource_ref:
            return None
        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("chat/completions")
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": _build_user_prompt(context)},
            ],
            "response_format": {"type": "json_object"},
            **completion_body_params(
                self._config.model_family or self._config.deployment,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            ),
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
        await record_gateway_route_evidence(
            response=response,
            target=self._target,
            model_role="t2.reasoner.primary",
            sink=self._gateway_route_sink,
        )
        envelope = response.json()
        if self._metering is not None:
            usage = extract_usage(envelope)
            if usage is not None:
                await self._metering.emit_safe(usage)
        return _parse_candidate(envelope, context)


def _build_user_prompt(context: T2ProposalContext) -> str:
    rules = [
        {
            "id": rule.id,
            "resource_type": rule.resource_type,
            "authorized_actions": [rule.remediates, *rule.alternatives],
            "check_logic_ref": rule.check_logic.reference,
        }
        for rule in context.allowed_rules
    ]
    return json.dumps(
        {
            "event_type": context.event.event_type,
            "target_resource_type": context.target_resource_type,
            "allowed_rules": rules,
            "instructions": (
                "Return a JSON object with abstain (boolean), action_type (string), "
                "params (object), cited_rule_ids (array), reasoning_trace (string). "
                "Use only listed rule ids and authorized actions."
            ),
        },
        sort_keys=True,
    )


def _parse_candidate(envelope: object, context: T2ProposalContext) -> QualityCandidate | None:
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("proposer response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content:
        raise RuntimeError("proposer response has no message content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("proposer returned non-JSON content") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("proposer response MUST be a JSON object")
    if parsed.get("abstain") is True:
        return None

    action_type = parsed.get("action_type")
    params = parsed.get("params", {})
    citations = parsed.get("cited_rule_ids", [])
    reasoning_trace = parsed.get("reasoning_trace", "")
    if not isinstance(action_type, str) or not action_type:
        raise RuntimeError("proposer response MUST carry a non-empty action_type")
    if not isinstance(params, dict):
        raise RuntimeError("proposer response params MUST be an object")
    if _contains_secret_key(params):
        raise RuntimeError("proposer response params contain a secret-like key")
    if (
        not isinstance(citations, list)
        or not citations
        or not all(isinstance(item, str) and item for item in citations)
    ):
        raise RuntimeError("proposer response cited_rule_ids MUST be a non-empty string array")
    if not isinstance(reasoning_trace, str):
        raise RuntimeError("proposer response reasoning_trace MUST be a string")

    allowed_by_id = {rule.id: rule for rule in context.allowed_rules}
    if any(rule_id not in allowed_by_id for rule_id in citations):
        raise RuntimeError("proposer cited a rule outside the allowed set")
    authorized_actions = {
        action
        for rule_id in citations
        for action in (
            allowed_by_id[rule_id].remediates,
            *allowed_by_id[rule_id].alternatives,
        )
    }
    if action_type not in authorized_actions:
        raise RuntimeError("proposer selected an action not authorized by its citations")

    return QualityCandidate(
        action_type=action_type,
        target_resource_ref=context.target_resource_ref,
        target_resource_type=context.target_resource_type,
        params=params,
        cited_rule_ids=tuple(citations),
        confidence_signals={
            "catalog_authorization": 1.0,
            "target_type_match": 1.0,
        },
        reasoning_trace=reasoning_trace[:4_000],
    )


def _contains_secret_key(value: Mapping[str, Any]) -> bool:
    for key, nested in value.items():
        normalized = str(key).lower().replace("-", "_")
        if any(part in _SECRET_KEYS for part in normalized.split("_")):
            return True
        if isinstance(nested, Mapping) and _contains_secret_key(nested):
            return True
    return False


__all__ = ["AzureOpenAIProposer", "AzureOpenAIProposerConfig"]
