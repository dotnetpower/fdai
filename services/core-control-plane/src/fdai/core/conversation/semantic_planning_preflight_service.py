"""Preflight operation for the semantic planning service."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from fdai_service_contracts.semantic_turn import SemanticConversationModelTier

from .conversation_preflight import ConversationPreflightResult
from .semantic_judgment import SemanticJudgmentBoundary
from .semantic_planning_preflight import DIRECT_RESPONSE_PROFILE
from .semantic_planning_support import _bounded_context
from .session import Turn


class SemanticPlanningPreflightMixin:
    """Provide preflight classification without granting query authority."""

    _semantic_judgment: SemanticJudgmentBoundary | None

    def preflight(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        locale: str,
        conversation_profile: Mapping[str, str] | None = None,
        cancelled: asyncio.Event | None = None,
        conversation_model_tier: SemanticConversationModelTier | None = None,
    ) -> ConversationPreflightResult:
        if self._semantic_judgment is None:
            return ConversationPreflightResult(proposal=None)
        response_profile = dict(DIRECT_RESPONSE_PROFILE)
        if conversation_profile is not None:
            response_profile["identity"] = conversation_profile["identity"]
            response_profile["role"] = conversation_profile["role"]
        return self._semantic_judgment.preflight(
            utterance=utterance,
            context=_bounded_context(prior_turns),
            locale=locale,
            direct_response_profile=response_profile,
            cancelled=cancelled,
            conversation_model_tier=conversation_model_tier,
        )


__all__ = ["SemanticPlanningPreflightMixin"]
