"""Azure OpenAI strict JSON model adapter for inert post-turn proposals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.core.learning import (
    NoImprovement,
    OperatorMemoryCandidate,
    PostTurnProposal,
    PostTurnReviewInput,
    RuleCandidateHint,
    SkillProposalDraft,
)
from fdai.core.operator_memory import MemoryCategory, ScopeKind
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class AzureOpenAIPostTurnModelConfig:
    endpoint: str
    deployment: str
    model_identity: str
    model_family: str
    system_prompt: str
    api_version: str = "2024-06-01"
    max_tokens: int = 2_048
    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None

    def __post_init__(self) -> None:
        if not self.model_identity.strip() or not self.model_family.strip():
            raise ValueError("post-turn model identity and family MUST be non-empty")
        if not self.system_prompt.strip():
            raise ValueError("post-turn system_prompt MUST be non-empty")
        if not 256 <= self.max_tokens <= 8_192:
            raise ValueError("post-turn max_tokens MUST be in [256, 8192]")
        if self.timeout_seconds <= 0:
            raise ValueError("post-turn timeout_seconds MUST be positive")


class AzureOpenAIPostTurnModel:
    """Call one model binding; consensus and authority stay in core."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIPostTurnModelConfig,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._config = config
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

    async def propose(
        self,
        review_input: PostTurnReviewInput,
    ) -> PostTurnProposal | NoImprovement:
        token = await self._identity.get_token(self._target.auth_audience)
        request = self._target.operation("chat/completions")
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": _review_prompt(review_input)},
            ],
            "temperature": 0.0,
            "max_tokens": self._config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
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
        except httpx.HTTPError as exc:
            raise RuntimeError(f"post-turn reviewer request failed: {type(exc).__name__}") from exc
        return _parse_response(response)


def _review_prompt(review_input: PostTurnReviewInput) -> str:
    return json.dumps(
        {
            "instructions": {
                "allowed_kinds": ["none", "operator_memory", "rule_hint", "skill_draft"],
                "evidence_must_be_subset_of": sorted(
                    {
                        *review_input.evidence_refs,
                        *(receipt.evidence_ref for receipt in review_input.tool_receipts),
                    }
                ),
                "operator_memory_scope": (
                    {
                        "kind": review_input.memory_scope_kind.value,
                        "ref": review_input.memory_scope_ref,
                    }
                    if review_input.memory_scope_kind is not None
                    else None
                ),
                "return": "one JSON object only",
            },
            "turn_data_trusted": False,
            "operator_body": review_input.operator_body,
            "assistant_body": review_input.assistant_body,
            "corrections": list(review_input.explicit_corrections),
            "validation_outcomes": list(review_input.validation_outcomes),
            "tool_receipts": [
                {
                    "tool_name": receipt.tool_name,
                    "status": receipt.status,
                    "evidence_ref": receipt.evidence_ref,
                }
                for receipt in review_input.tool_receipts
            ],
        },
        sort_keys=True,
    )


def _parse_response(response: httpx.Response) -> PostTurnProposal | NoImprovement:
    try:
        envelope = response.json()
        choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, Mapping) else None
        parsed = json.loads(content) if isinstance(content, str) else None
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("post-turn reviewer returned invalid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise RuntimeError("post-turn reviewer content MUST be a JSON object")
    kind = _string(parsed, "kind")
    if kind == "none":
        return NoImprovement(_string(parsed, "reason"))
    evidence_refs = _string_tuple(parsed, "evidence_refs")
    confidence = _confidence(parsed)
    if kind == "operator_memory":
        return OperatorMemoryCandidate(
            scope_kind=ScopeKind(_string(parsed, "scope_kind")),
            scope_ref=_string(parsed, "scope_ref"),
            category=MemoryCategory(_string(parsed, "category")),
            body=_string(parsed, "body"),
            evidence_refs=evidence_refs,
            confidence=confidence,
        )
    if kind == "skill_draft":
        return SkillProposalDraft(
            skill_name=_string(parsed, "skill_name"),
            markdown=_string(parsed, "markdown").encode(),
            evidence_refs=evidence_refs,
            confidence=confidence,
        )
    if kind == "rule_hint":
        return RuleCandidateHint(
            proposal_kind=_string(parsed, "proposal_kind"),
            target_ref=_string(parsed, "target_ref"),
            pattern=_string(parsed, "pattern"),
            evidence_refs=evidence_refs,
            confidence=confidence,
        )
    raise RuntimeError("post-turn reviewer returned an unsupported proposal kind")


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RuntimeError(f"post-turn reviewer field {key!r} MUST be a non-empty string")
    return item


def _string_tuple(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
        raise RuntimeError(f"post-turn reviewer field {key!r} MUST be a string array")
    return tuple(item)


def _confidence(value: Mapping[str, object]) -> float:
    item = value.get("confidence")
    if not isinstance(item, int | float) or isinstance(item, bool):
        raise RuntimeError("post-turn reviewer confidence MUST be numeric")
    return float(item)


__all__ = ["AzureOpenAIPostTurnModel", "AzureOpenAIPostTurnModelConfig"]
