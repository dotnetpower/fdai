"""AzureOpenAIRcaModel - httpx-based T2 root-cause proposal client.

Implements the :class:`~fdai.core.rca.llm.RcaModel` seam by calling
Azure OpenAI ``chat/completions`` with JSON output. The adapter only
builds the prompt, makes the call, and returns the model's raw content
string; the deterministic parse + grounding
(:func:`~fdai.core.rca.llm.parse_rca_response`) is the authority over
that text, never this adapter. A malformed transport envelope raises so
the caller (``LlmRcaReasoner``) turns it into an abstain rather than
silently accepting garbage.

The user prompt lists the caller-supplied ``candidate_citations`` and
instructs the model to cite only those refs; the parser refuses any
other ref (prompt-injection defense), so grounding does not depend on
the model's cooperation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.prompts import (
    PromptProfileEvidence,
    PromptReplayManifest,
    estimate_prompt_tokens,
    estimate_serialized_request_tokens,
)
from fdai.core.rca import Citation
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.model_trace import prepare_model_messages
from fdai.delivery.azure.llm.request_target import (
    COGNITIVE_SERVICES_SCOPE,
    ModelRequestTarget,
)
from fdai.delivery.azure.llm.usage import extract_usage
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class AzureOpenAIRcaModelConfig:
    """Endpoint + deployment binding for the T2 RCA reasoner.

    ``system_prompt`` is required and MUST be composed at the
    composition root (catalog-as-code), never a code literal - the same
    rule as the cross-check adapter.
    """

    endpoint: str
    deployment: str
    system_prompt: str
    prompt_manifest: PromptReplayManifest | None = None
    api_version: str = "2024-06-01"
    temperature: float = 0.0
    max_tokens: int = 512
    model_family: str | None = None
    timeout_seconds: float = 30.0
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None


class AzureOpenAIRcaModel:
    """RCA reasoner model backed by Azure OpenAI chat completions."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAIRcaModelConfig,
        metering: MeteringEmitter | None = None,
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
        if config.prompt_manifest is not None:
            if (
                config.prompt_manifest.system_text_sha256
                != hashlib.sha256(config.system_prompt.encode()).hexdigest()
            ):
                raise ValueError("RCA prompt manifest does not match system_prompt")
            if (
                config.prompt_manifest.reserved_output_tokens is not None
                and config.prompt_manifest.reserved_output_tokens < config.max_tokens
            ):
                raise ValueError("RCA max_tokens exceeds prompt output reserve")
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

    @property
    def prompt_profile_evidence(self) -> PromptProfileEvidence | None:
        manifest = self._config.prompt_manifest
        return PromptProfileEvidence.from_manifest(manifest) if manifest is not None else None

    async def propose_cause(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> str:
        """Call the model and return its raw JSON content string."""
        request = self._target.operation("chat/completions")
        user_prompt = _build_user_prompt(incident_summary, candidate_citations)
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            **completion_body_params(
                self._config.model_family or self._config.deployment,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            ),
        }
        body["messages"] = list(prepare_model_messages(body["messages"]).messages)
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        manifest = self._config.prompt_manifest
        if manifest is not None:
            system_content = body["messages"][0]["content"]
            if not isinstance(system_content, str):
                raise RuntimeError("RCA system message is invalid")
            if (
                manifest.system_token_budget is not None
                and estimate_prompt_tokens(system_content) > manifest.system_token_budget
            ):
                raise RuntimeError("RCA system prompt exceeds profile budget")
            if (
                manifest.request_token_budget is not None
                and estimate_serialized_request_tokens(
                    body,
                    reserved_output_tokens=self._config.max_tokens,
                )
                > manifest.request_token_budget
            ):
                raise RuntimeError("RCA request exceeds profile budget")
        token = await self._identity.get_token(self._target.auth_audience)
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
        if self._metering is not None:
            usage = extract_usage(envelope)
            if usage is not None:
                await self._metering.emit_safe(usage)
        return _extract_content(envelope)


def _build_user_prompt(incident_summary: str, candidate_citations: Sequence[Citation]) -> str:
    """Build the grounding-constrained user message (JSON)."""
    return json.dumps(
        {
            "incident": incident_summary,
            "available_citations": [f"{c.kind.value}:{c.ref}" for c in candidate_citations],
            "citation_refs": [c.ref for c in candidate_citations],
            "evidence_facts": [
                {"ref": citation.ref, "facts": list(citation.facts)}
                for citation in candidate_citations
                if citation.facts
            ],
            "instructions": (
                "Identify the most likely root cause. Respond with a JSON object "
                '{"cause": string, "cause_domain": one of infrastructure, application, '
                "shared_dependency, external_provider, mixed, unknown, "
                '"confidence": number in [0,1], "citations": '
                "[ref, ...]}. Cite ONLY refs listed in citation_refs; do not "
                "invent references."
            ),
        },
        sort_keys=True,
    )


def _extract_content(envelope: Any) -> str:
    """Pull the assistant message content out of a chat-completions envelope."""
    choices = envelope.get("choices") if isinstance(envelope, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("rca model response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content:
        raise RuntimeError("rca model response has no message content")
    return content


__all__ = ["AzureOpenAIRcaModel", "AzureOpenAIRcaModelConfig"]
