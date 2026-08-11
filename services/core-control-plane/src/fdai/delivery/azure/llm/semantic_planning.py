"""Azure OpenAI adapter for bounded semantic frame and query-plan proposals."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from fdai_service_contracts.ontology_query import SemanticProblemFrame
from pydantic import BaseModel

from fdai.core.conversation.semantic_planning_models import (
    QueryPlanProposal,
    SemanticFrameProposal,
)
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 8
_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_DESCRIPTORS = 512
_MAX_PROMPT_BYTES = 786_432
_MAX_RESPONSE_BYTES = 65_536
_MAX_SYSTEM_PROMPT_CHARS = 16_384
_ProposalT = TypeVar("_ProposalT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AzureOpenAISemanticPlanningModelConfig:
    """Bounded request targets and catalog-owned semantic planning prompts."""

    candidates: tuple[ModelRequestTarget, ...]
    frame_system_prompt: str
    plan_system_prompt: str
    timeout_seconds: float = 30.0
    max_tokens: int = 2_048

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"semantic planning candidates MUST contain 1 to {_MAX_CANDIDATES}")
        identities = tuple(
            (candidate.endpoint, candidate.deployment, candidate.api_version)
            for candidate in self.candidates
        )
        if len(identities) != len(set(identities)):
            raise ValueError("semantic planning candidates MUST be unique")
        for prompt in (self.frame_system_prompt, self.plan_system_prompt):
            if not prompt or len(prompt) > _MAX_SYSTEM_PROMPT_CHARS:
                raise ValueError("semantic planning system prompts MUST be non-empty and bounded")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("semantic planning timeout_seconds MUST be in (0, 120]")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("semantic planning max_tokens MUST be in [1, 4096]")


class AzureOpenAISemanticPlanningModel:
    """Synchronously propose two validated JSON records over async Azure I/O.

    Calls must run outside ``owner_loop``. ``SemanticConversationRuntime``
    provides that boundary with ``asyncio.to_thread``. The adapter schedules
    workload-identity and HTTP work back onto the owning runtime loop, tries
    candidates in configured order, and returns ``None`` after any bounded
    all-candidate failure without exposing provider details.
    """

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAISemanticPlanningModelConfig,
        owner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        if not owner_loop.is_running():
            raise ValueError("semantic planning owner_loop MUST be running")
        self._identity = identity
        self._http = http_client
        self._config = config
        self._owner_loop = owner_loop

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
    ) -> Mapping[str, Any] | None:
        """Return one validated frame proposal or ``None`` on bounded failure."""

        payload = {
            "utterance": utterance,
            "context": context,
            "descriptors": descriptors,
            "principal_role": principal_role,
            "purpose": purpose,
        }
        if not _bounded_input(payload, context=context, descriptors=descriptors):
            return None
        return self._complete(
            payload=payload,
            prompt=self._config.frame_system_prompt,
            proposal_type=SemanticFrameProposal,
            operation="frame",
        )

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
    ) -> Mapping[str, Any] | None:
        """Return one validated query-plan proposal or ``None`` on bounded failure."""

        payload = {
            "frame": frame.model_dump(mode="json"),
            "descriptors": descriptors,
            "principal_role": principal_role,
            "purpose": purpose,
        }
        if not _bounded_input(payload, context=(), descriptors=descriptors):
            return None
        return self._complete(
            payload=payload,
            prompt=self._config.plan_system_prompt,
            proposal_type=QueryPlanProposal,
            operation="plan",
        )

    def _complete(
        self,
        *,
        payload: Mapping[str, Any],
        prompt: str,
        proposal_type: type[BaseModel],
        operation: str,
    ) -> dict[str, Any] | None:
        future = asyncio.run_coroutine_threadsafe(
            self._complete_async(
                payload=payload,
                prompt=prompt,
                proposal_type=proposal_type,
                operation=operation,
            ),
            self._owner_loop,
        )
        try:
            return future.result(timeout=self._config.timeout_seconds + 1)
        except Exception as exc:  # noqa: BLE001 - provider details remain inside the adapter
            future.cancel()
            _LOGGER.warning(
                "semantic_planning_model_unavailable",
                extra={"operation": operation, "failure_type": type(exc).__name__},
            )
            return None

    async def _complete_async(
        self,
        *,
        payload: Mapping[str, Any],
        prompt: str,
        proposal_type: type[BaseModel],
        operation: str,
    ) -> dict[str, Any] | None:
        user_content = json.dumps(
            {"untrusted_input": payload},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        schema = json.dumps(
            proposal_type.model_json_schema(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        system_content = f"{prompt}\nRequired JSON Schema:\n{schema}"
        candidate_timeout = self._config.timeout_seconds / len(self._config.candidates)
        for index, target in enumerate(self._config.candidates):
            try:
                async with asyncio.timeout(candidate_timeout):
                    token = await self._identity.get_token(target.auth_audience)
                    request = target.operation("chat/completions")
                    body: dict[str, Any] = {
                        "messages": [
                            {"role": "system", "content": system_content},
                            {"role": "user", "content": user_content},
                        ],
                        "response_format": {"type": "json_object"},
                        **completion_body_params(
                            target.deployment,
                            temperature=0.0,
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
                        timeout=candidate_timeout,
                    )
                    response.raise_for_status()
                    return _validated_content(response, proposal_type)
            except Exception:  # noqa: BLE001 - bounded fallback hides provider details
                _LOGGER.warning(
                    "semantic_planning_candidate_failed",
                    extra={"operation": operation, "candidate_index": index},
                )
        return None


def _bounded_input(
    payload: Mapping[str, Any],
    *,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    if len(context) > _MAX_CONTEXT_ITEMS or sum(len(item) for item in context) > _MAX_CONTEXT_CHARS:
        return False
    if len(descriptors) > _MAX_DESCRIPTORS:
        return False
    try:
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False, sort_keys=True).encode()
    except (TypeError, ValueError):
        return False
    return len(encoded) <= _MAX_PROMPT_BYTES


def _validated_content(  # noqa: UP047 - pinned mypy does not parse PEP 695 functions
    response: httpx.Response,
    proposal_type: type[_ProposalT],
) -> dict[str, Any]:
    envelope = response.json()
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError("semantic planning response has no choice")
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content or len(content.encode()) > _MAX_RESPONSE_BYTES:
        raise ValueError("semantic planning response content is unavailable or oversized")
    proposal = proposal_type.model_validate_json(content)
    return proposal.model_dump(mode="json")


__all__ = [
    "AzureOpenAISemanticPlanningModel",
    "AzureOpenAISemanticPlanningModelConfig",
]
