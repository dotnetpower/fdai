"""Speculative form-path start for the semantic planning service."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.conversation.semantic_stored_result_handles import StoredReferenceContext
from fdai.core.ontology_platform import OntologyQueryPlanVerifier

from .semantic_compiled_answers import (
    CompiledAnswerPath,
    CompiledAnswerTicket,
    start_compiled_answer,
)
from .semantic_planning_models import QueryManifestProvider
from .semantic_planning_support import _bounded_context
from .session import Principal, Turn


class SemanticPlanningSpeculationMixin:
    """Start the form path before the preflight returns, when the local setting allows it.

    The preflight keeps its routing authority: a ticket only runs reads that the form path
    would run anyway, and the planner adopts it for the same question or cancels it unused.
    """

    _compiled_answers: CompiledAnswerPath | None
    _manifests: QueryManifestProvider
    _verifier: OntologyQueryPlanVerifier

    @property
    def speculative_form_enabled(self) -> bool:
        return self._compiled_answers is not None and self._compiled_answers.speculative_start

    def start_speculative_form(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        principal: Principal,
        purpose: str,
        locale: str,
        stored_reference_context: StoredReferenceContext | None = None,
    ) -> CompiledAnswerTicket | None:
        """Return a started ticket for an unbound, document-free turn, or ``None``.

        The caller confirms the turn has no bound incident, investigation, resource context,
        or document evidence, which are the planner's own eligibility conditions.
        """

        path = self._compiled_answers
        if path is None or not path.speculative_start:
            return None
        if not utterance.strip() or len(utterance) > 32_000:
            return None
        manifest = self._manifests.manifest_for(principal=principal, purpose=purpose)
        if (
            manifest.principal_role.value != principal.role.value
            or purpose not in manifest.purposes
        ):
            return None
        return start_compiled_answer(
            path,
            eligible=True,
            utterance=utterance,
            context=_bounded_context(prior_turns),
            locale=locale,
            manifest=manifest,
            verifier=self._verifier,
            principal=principal,
            purpose=purpose,
            stored_reference_context=stored_reference_context,
        )


__all__ = ["SemanticPlanningSpeculationMixin"]
