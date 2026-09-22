"""Model invocation boundary for conversation preflight routing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticDirectResponseDraft
from fdai_service_contracts.semantic_turn import SemanticConversationModelTier
from pydantic import ValidationError

from .conversation_preflight_contracts import (
    CancellableConversationPreflightModel,
    ContextDependency,
    ConversationPreflightBinding,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    GeneralKnowledgeSignal,
    OperationalSignal,
    SocialAct,
    SocialResponseNarratorBinding,
    SocialResponseNarratorResult,
)
from .conversation_preflight_validation import (
    bounded_context as _bounded_context,
)
from .conversation_preflight_validation import (
    bounded_profile as _bounded_profile,
)
from .conversation_preflight_validation import (
    preflight_input_digest as _preflight_input_digest,
)
from .conversation_preflight_validation import (
    repair_instruction as _repair_instruction,
)
from .model_observation import ConversationModelObservation, ConversationModelResponse

_MAX_UTTERANCE_CHARS = 32_000
_MAX_SCHEMA_ATTEMPTS = 2
_ROUTE_PROMOTION_CONFIDENCE = 0.9
_LOGGER = logging.getLogger("fdai.core.conversation.conversation_preflight")


class ConversationPreflightBoundary:
    """Run one compact T1 attempt and fail open only to full semantic judgment."""

    def __init__(
        self,
        *,
        binding: ConversationPreflightBinding | None,
        t2_binding: ConversationPreflightBinding | None = None,
        narrator: SocialResponseNarratorBinding | None = None,
    ) -> None:
        self._binding = binding
        self._t2_binding = t2_binding
        self._narrator = narrator

    def classify(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        cancelled: asyncio.Event | None = None,
        conversation_model_tier: SemanticConversationModelTier | None = None,
    ) -> ConversationPreflightResult:
        """Return a validated candidate or no proposal for full-path continuation."""

        binding = (
            self._t2_binding
            if conversation_model_tier is SemanticConversationModelTier.T2
            else self._binding
        )
        if binding is None or not utterance.strip() or len(utterance) > _MAX_UTTERANCE_CHARS:
            return ConversationPreflightResult(proposal=None)
        try:
            bounded_context = _bounded_context(context)
            bounded_profile = _bounded_profile(direct_response_profile)
        except (TypeError, ValueError):
            return ConversationPreflightResult(proposal=None)
        response_locale = "ko" if locale.casefold().startswith("ko") else "en"
        profile_digest = content_digest(bounded_profile)
        observations: list[ConversationModelObservation] = []
        schema_repair: tuple[dict[str, str], ...] = ()
        for attempt in range(_MAX_SCHEMA_ATTEMPTS):
            try:
                if binding.supports_cancellation:
                    response = cast(
                        CancellableConversationPreflightModel,
                        binding.model,
                    ).preflight(
                        utterance=utterance,
                        context=bounded_context,
                        locale=response_locale,
                        direct_response_profile=bounded_profile,
                        direct_response_profile_digest=profile_digest,
                        schema_repair=schema_repair,
                        cancelled=cancelled,
                    )
                else:
                    response = binding.model.preflight(
                        utterance=utterance,
                        context=bounded_context,
                        locale=response_locale,
                        direct_response_profile=bounded_profile,
                        direct_response_profile_digest=profile_digest,
                        schema_repair=schema_repair,
                    )
            except Exception as exc:  # noqa: BLE001 - full judgment remains the safe fallback
                _LOGGER.warning(
                    "conversation_preflight_model_failed",
                    extra={"failure_type": type(exc).__name__},
                )
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="provider_unavailable",
                )
            if response is None:
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="provider_unavailable",
                )
            raw: Mapping[str, Any]
            if isinstance(response, ConversationModelResponse):
                raw = response.proposal
                observations.append(response.observation)
            else:
                raw = response
            try:
                proposal = ConversationPreflightProposal.model_validate(raw)
            except (TypeError, ValueError, ValidationError) as exc:
                repair = _repair_instruction(exc)
                if repair is not None and attempt + 1 < _MAX_SCHEMA_ATTEMPTS:
                    schema_repair = (repair,)
                    continue
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="malformed",
                )
            return ConversationPreflightResult(
                proposal=proposal,
                observations=tuple(observations),
                attempted=True,
                input_digest=_preflight_input_digest(utterance),
                proposal_digest=content_digest(proposal.model_dump(mode="json")),
                model_config_digest=binding.model_config_digest,
                prompt_digest=binding.prompt_digest,
                direct_response_profile_digest=profile_digest,
            )
        raise RuntimeError("conversation preflight attempt bound is unreachable")

    def narrate_social(
        self,
        *,
        utterance: str,
        locale: str,
        social_act: SocialAct,
        continued: bool,
        direct_response_profile: Mapping[str, Any],
    ) -> SocialResponseNarratorResult:
        """Author one response without exposing operational context or capabilities."""

        if self._narrator is None:
            return SocialResponseNarratorResult(draft=None)
        response_locale = "ko" if locale.casefold().startswith("ko") else "en"
        try:
            bounded_profile = _bounded_profile(direct_response_profile)
        except (TypeError, ValueError):
            return SocialResponseNarratorResult(draft=None)
        profile_digest = content_digest(bounded_profile)
        try:
            response = self._narrator.model.narrate_social(
                utterance=utterance,
                locale=response_locale,
                social_act=social_act.value,
                continued=continued,
                direct_response_profile=bounded_profile,
                direct_response_profile_digest=profile_digest,
            )
        except Exception as exc:  # noqa: BLE001 - terminal hold is the safe fallback
            _LOGGER.warning(
                "social_response_narrator_failed",
                extra={"failure_type": type(exc).__name__},
            )
            return SocialResponseNarratorResult(draft=None, attempted=True)
        if response is None:
            return SocialResponseNarratorResult(draft=None, attempted=True)
        observation: ConversationModelObservation | None = None
        raw: Mapping[str, Any]
        if isinstance(response, ConversationModelResponse):
            raw = response.proposal
            observation = response.observation
        else:
            raw = response
        try:
            draft = SemanticDirectResponseDraft.model_validate(raw)
            if draft.locale != response_locale or draft.profile_digest != profile_digest:
                raise ValueError("social response narrator binding mismatch")
        except (TypeError, ValueError, ValidationError):
            return SocialResponseNarratorResult(
                draft=None,
                observations=(observation,) if observation is not None else (),
                attempted=True,
            )
        return SocialResponseNarratorResult(
            draft=draft,
            observations=(observation,) if observation is not None else (),
            attempted=True,
        )


def preflight_selects_general_knowledge(
    result: ConversationPreflightResult | None,
    *,
    utterance: str,
    locale: str,
) -> bool:
    """Accept only one confident context-independent general-knowledge route."""
    if result is None:
        return False
    proposal = result.proposal
    return bool(
        result.attempted
        and result.failure_kind is None
        and proposal is not None
        and proposal.social_act is SocialAct.NONE
        and proposal.knowledge_signal is GeneralKnowledgeSignal.EXPLICIT
        and proposal.operational_signal is OperationalSignal.NONE
        and proposal.context_dependency is ContextDependency.NONE
        and proposal.confidence >= _ROUTE_PROMOTION_CONFIDENCE
        and result.input_digest == _preflight_input_digest(utterance)
        and result.proposal_digest == content_digest(proposal.model_dump(mode="json"))
        and result.model_config_digest is not None
        and result.prompt_digest is not None
        and proposal.general_answer is not None
        and proposal.general_answer.locale == ("ko" if locale.casefold().startswith("ko") else "en")
        and proposal.general_answer.profile_digest == result.direct_response_profile_digest
    )
