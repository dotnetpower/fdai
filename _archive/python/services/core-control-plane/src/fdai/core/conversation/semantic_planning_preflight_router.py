"""Preflight-driven direct-response routing for one `plan()` invocation.

Owns the small piece of mutable state a `SemanticPlanningService.plan` call
threads through its optional preflight classifier: whether preflight ran, the
observed social act, whether it vetoes a direct social response, and the
accumulated model observations. Extracted so the orchestrating `plan` method
stays a linear stage sequence instead of inlining nested closures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .conversation_preflight import (
    DIRECT_SOCIAL_ACTS,
    ContextDependency,
    ConversationPreflightResult,
    OperationalSignal,
    SocialAct,
)
from .semantic_judgment import SemanticJudgmentBoundary, SemanticJudgmentObservation
from .semantic_planning_models import (
    SemanticDirectResponseIntent,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from .semantic_planning_preflight import PREFLIGHT_DIRECT_CONFIDENCE
from .semantic_planning_support import _outcome


class PreflightDirectResponseRouter:
    """Route one bounded turn through the optional preflight classifier."""

    def __init__(
        self,
        *,
        semantic_judgment: SemanticJudgmentBoundary | None,
        utterance: str,
        locale: str,
        response_profile: Mapping[str, Any],
        unbound_conversation: bool,
        supplied_preflight_result: ConversationPreflightResult | None,
        model_observations: list[SemanticJudgmentObservation],
        speculative_ticket: Any = None,
    ) -> None:
        self._semantic_judgment = semantic_judgment
        self._utterance = utterance
        self._locale = locale
        self._response_profile = response_profile
        self._unbound_conversation = unbound_conversation
        self._supplied_preflight_result = supplied_preflight_result
        self._supplied_preflight_consumed = False
        self._speculative_ticket = speculative_ticket
        self.model_observations = model_observations
        self.ran = False
        self.social_act = SocialAct.NONE
        self.vetoes_direct = False
        self.effective_result: ConversationPreflightResult | None = None

    def run(self, context: Sequence[str]) -> SemanticPlanningOutcome | None:
        """Return a direct-response outcome, or None to continue planning."""
        if self._semantic_judgment is None:
            return None
        self.ran = True
        if self._supplied_preflight_result is not None and not self._supplied_preflight_consumed:
            preflight = self._supplied_preflight_result
            self._supplied_preflight_consumed = True
        else:
            preflight = self._semantic_judgment.preflight(
                utterance=self._utterance,
                context=context,
                locale=self._locale,
                direct_response_profile=self._response_profile,
            )
        self.effective_result = preflight
        self.model_observations.extend(preflight.observations)
        self.vetoes_direct = preflight.failure_kind == "malformed"
        proposal = preflight.proposal
        if proposal is None:
            return None
        self.vetoes_direct = (
            proposal.social_act is SocialAct.ACKNOWLEDGEMENT
            or proposal.operational_signal is not OperationalSignal.NONE
            or proposal.context_dependency
            not in {ContextDependency.NONE, ContextDependency.SOCIAL_CONTINUITY}
        )
        self.social_act = proposal.social_act
        direct_intent = (
            SemanticDirectResponseIntent.SELF_INTRODUCTION
            if proposal.social_act is SocialAct.SELF_INTRODUCTION
            else SemanticDirectResponseIntent.GREETING
            if proposal.social_act in DIRECT_SOCIAL_ACTS
            else None
        )
        if (
            direct_intent is None
            or proposal.confidence < PREFLIGHT_DIRECT_CONFIDENCE
            or proposal.operational_signal is not OperationalSignal.NONE
            or proposal.context_dependency
            not in {ContextDependency.NONE, ContextDependency.SOCIAL_CONTINUITY}
            or not self._unbound_conversation
        ):
            return None
        narrated = self._semantic_judgment.narrate_social(
            utterance=self._utterance,
            locale=self._locale,
            social_act=proposal.social_act,
            continued=proposal.context_dependency is ContextDependency.SOCIAL_CONTINUITY,
            direct_response_profile=self._response_profile,
        )
        self.model_observations.extend(narrated.observations)
        response = narrated.draft
        if response is None:
            return _outcome(
                SemanticPlanningDisposition.UNAVAILABLE,
                "social_response_narrator_unavailable",
                social_act=proposal.social_act,
            )
        return _outcome(
            SemanticPlanningDisposition.DIRECT_RESPONSE,
            "conversation_preflight_direct_response",
            direct_response_intent=direct_intent,
            direct_response_answer=response.answer,
            social_act=proposal.social_act,
        )

    def finish(self, outcome: SemanticPlanningOutcome) -> SemanticPlanningOutcome:
        """Stamp the recorded observations and social act onto a final outcome."""
        if self._speculative_ticket is not None:
            self._speculative_ticket.cancel()
            existing = {id(item) for item in self.model_observations}
            self.model_observations.extend(
                item
                for item in getattr(self._speculative_ticket, "observations", ())
                if id(item) not in existing
            )
            self._speculative_ticket = None
        updated = outcome
        recorded_observations = tuple(self.model_observations)
        if recorded_observations and outcome.model_observations != recorded_observations:
            updated = replace(updated, model_observations=recorded_observations)
        if updated.social_act is not self.social_act:
            updated = replace(updated, social_act=self.social_act)
        return updated


__all__ = ["PreflightDirectResponseRouter"]
