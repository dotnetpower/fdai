"""Generate and verify one JSON conversation answer."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    LatencyRoutedChatBackend,
)
from fdai.delivery.operator_api.application.conversation.busy_input import (
    answer_with_busy_input,
    await_with_interrupt,
)
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    render_system_health_answer,
)
from fdai.delivery.operator_api.application.conversation.evidence.enrichment import (
    _delegation_summary,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    freshness_evidence_refs,
    response_evidence_freshness_context,
)
from fdai.delivery.operator_api.application.conversation.planning import planning_metadata
from fdai.delivery.operator_api.application.conversation.post_generation import (
    review_korean_narrator_answer,
    verify_quality_result,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _concept_answer,
    _ontology_browse_answer,
    _response_locale,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    BackendChatHistoryCompressor,
    ChatHistoryPolicy,
    answer_with_content_policy_recovery,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    ResponseCompletionDependencies,
    metering_correlation_id,
    turn_metadata,
    uses_evidence_fast_path,
)
from fdai.delivery.operator_api.application.conversation.review_submission import (
    PostTurnReviewSubmission,
    explicit_corrections,
)
from fdai.delivery.operator_api.application.conversation.verification import (
    AnswerVerification,
    verify_answer,
)
from fdai.delivery.operator_api.persistence.conversation import (
    append_assistant_turn,
    replay_metadata,
)
from fdai.delivery.operator_api.projections.conversation.document_evidence import (
    merge_document_verification,
)
from fdai.delivery.operator_api.projections.conversation.presentation import (
    response_presentation_artifact,
    select_answer_presentation,
)
from fdai.delivery.operator_api.projections.conversation.provenance import (
    web_search_summary as _web_search_summary,
)
from fdai.delivery.operator_api.projections.conversation.resource_context import (
    resource_followup_verification,
    response_resource_context,
)
from fdai.delivery.operator_api.projections.conversation.screen_data import (
    render_screen_data_answer,
)
from fdai.delivery.operator_api.projections.conversation.terminal import (
    assurance_policy_summary,
    public_intent_graph_evidence,
    response_incident_candidates,
    response_llm_usage_analysis_context,
    response_llm_usage_chart_artifact,
    response_resource_result_context,
    response_source_failure_context,
)
from fdai.shared.telemetry.correlation import with_correlation


@dataclass(frozen=True, slots=True)
class GeneratedJsonTurn:
    """Verified generation state passed to terminal response completion."""

    reply: dict[str, Any]
    verification: AnswerVerification
    answer_plan: Any
    history_metadata: dict[str, Any]


class JsonTurnGenerator:
    """Select, generate, quality-review, and verify a one-shot answer."""

    def __init__(
        self,
        *,
        backend: ChatBackend,
        busy_input_coordinator: BusyInputCoordinator | None,
        history_compressor: BackendChatHistoryCompressor,
        history_policy: ChatHistoryPolicy,
    ) -> None:
        self._backend = backend
        self._busy_input_coordinator = busy_input_coordinator
        self._history_compressor = history_compressor
        self._history_policy = history_policy

    async def generate(
        self,
        *,
        principal_id: str,
        session_id: str,
        clean_prompt: str,
        history: list[dict[str, str]],
        history_metadata: dict[str, Any],
        preferred_model: str | None,
        view_context: dict[str, Any],
        answer_plan: Any,
        active_turn: Any | None,
        response_locale: str | None,
        resource_context: Any,
        resource_followup: bool,
        freshness_context: Any,
        freshness_answer: str | None,
        document_evidence_refs: tuple[str, ...],
    ) -> GeneratedJsonTurn:
        """Return the verified answer and any recovered history metadata."""

        health_answer = render_system_health_answer(view_context, locale=response_locale)
        screen_answer = render_screen_data_answer(
            clean_prompt,
            view_context,
            locale=response_locale,
        )
        concept_answer = (
            _concept_answer(view_context, answer_plan) if response_locale is None else None
        )
        ontology_answer = _ontology_browse_answer(
            clean_prompt,
            view_context,
            locale=response_locale,
        )
        contextual_verification = (
            resource_followup_verification(view_context, resource_context)
            if resource_followup
            else None
        )
        freshness_verification = (
            AnswerVerification(
                status="verified",
                answer=freshness_answer,
                authority="server_evidence_freshness",
                checks_completed=1,
                checks_total=1,
                evidence_refs=freshness_evidence_refs(freshness_context),
                reason_code="evidence_freshness_grounded",
            )
            if freshness_answer is not None and freshness_context is not None
            else None
        )
        if uses_evidence_fast_path(view_context):
            with (
                with_correlation(metering_correlation_id(principal_id, session_id)),
                with_invocation_scope(InvocationScope.OPERATOR_CHAT),
            ):
                presentation_decision = await await_with_interrupt(
                    select_answer_presentation(
                        backend=object(),
                        prompt=clean_prompt,
                        plan=answer_plan,
                        view_context=view_context,
                    ),
                    active_turn=active_turn,
                )
                answer_plan = presentation_decision.answer_plan
                if presentation_decision.presentation_plan is not None:
                    view_context["_presentation_plan"] = (
                        presentation_decision.presentation_plan.to_dict()
                    )
            view_context["_answer_plan"] = answer_plan.to_dict()
        verification: AnswerVerification
        if freshness_verification is not None:
            verification = freshness_verification
            reply = {
                "answer": verification.answer,
                "model": "evidence-freshness",
                "source": "evidence:freshness",
                "verification": verification.to_dict(),
            }
        elif contextual_verification is not None:
            verification = contextual_verification
            reply = {
                "answer": verification.answer,
                "model": "heimdall-read-investigation",
                "source": "evidence:read-investigation",
                "verification": verification.to_dict(),
            }
        elif uses_evidence_fast_path(view_context):
            canonical = verify_answer(
                "",
                view_context,
                locale=_response_locale(clean_prompt, view_context),
            )
            verification = verify_answer(
                canonical.answer,
                view_context,
                locale=_response_locale(clean_prompt, view_context),
            )
            reply = {
                "answer": verification.answer,
                "model": "evidence-verifier",
                "source": f"evidence:{verification.status}",
                "verification": verification.to_dict(),
            }
        elif ontology_answer is not None:
            verification = verify_answer(ontology_answer, view_context, locale=response_locale)
            reply = {
                "answer": verification.answer,
                "model": "ontology-snapshot",
                "source": "evidence:ontology-snapshot",
                "verification": verification.to_dict(),
            }
        elif health_answer is not None:
            verification = verify_answer(health_answer, view_context, locale=response_locale)
            reply = {
                "answer": verification.answer,
                "model": "read-model-health",
                "source": "evidence:system-health",
                "verification": verification.to_dict(),
            }
        elif screen_answer is not None:
            verification = verify_answer(screen_answer, view_context, locale=response_locale)
            reply = {
                "answer": verification.answer,
                "model": "bragi-screen-t0",
                "source": "evidence:current-screen",
                "verification": verification.to_dict(),
            }
        elif concept_answer is not None:
            verification = verify_answer(concept_answer, view_context, locale=None)
            reply = {
                "answer": verification.answer,
                "model": "concept-glossary",
                "source": "evidence:fdai-glossary",
                "verification": verification.to_dict(),
            }
        else:
            reply, verification, history_metadata = await self._generate_backend_reply(
                principal_id=principal_id,
                session_id=session_id,
                clean_prompt=clean_prompt,
                history=history,
                history_metadata=history_metadata,
                preferred_model=preferred_model,
                view_context=view_context,
                active_turn=active_turn,
                response_locale=response_locale,
            )
        verification = merge_document_verification(verification, document_evidence_refs)
        return GeneratedJsonTurn(
            reply={
                **reply,
                "answer": verification.answer,
                "verification": verification.to_dict(),
            },
            verification=verification,
            answer_plan=answer_plan,
            history_metadata=history_metadata,
        )

    async def _generate_backend_reply(
        self,
        *,
        principal_id: str,
        session_id: str,
        clean_prompt: str,
        history: list[dict[str, str]],
        history_metadata: dict[str, Any],
        preferred_model: str | None,
        view_context: dict[str, Any],
        active_turn: Any | None,
        response_locale: str | None,
    ) -> tuple[dict[str, Any], AnswerVerification, dict[str, Any]]:
        async def invoke_backend(active_history: list[dict[str, str]]) -> dict[str, Any]:
            nonlocal history_metadata

            async def invoke_raw(candidate_history: list[dict[str, str]]) -> dict[str, Any]:
                if isinstance(self._backend, LatencyRoutedChatBackend):
                    return await self._backend.answer(
                        prompt=clean_prompt,
                        view_context=view_context,
                        history=candidate_history,
                        preferred_model=preferred_model,
                    )
                return await self._backend.answer(
                    prompt=clean_prompt,
                    view_context=view_context,
                    history=candidate_history,
                )

            backend_reply, recovery = await answer_with_content_policy_recovery(
                invoke=invoke_raw,
                history=active_history,
                compressor=self._history_compressor,
                policy=self._history_policy,
            )
            if recovery is not None:
                history_metadata = recovery.metadata()
            return backend_reply

        with (
            with_correlation(metering_correlation_id(principal_id, session_id)),
            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
        ):
            draft_reply = await answer_with_busy_input(
                invoke=invoke_backend,
                history=history,
                coordinator=self._busy_input_coordinator,
                active_turn=active_turn,
            )
        provisional_answer = str(draft_reply.get("answer", ""))

        async def invoke_quality(
            quality_prompt: str,
            quality_context: dict[str, Any],
        ) -> dict[str, Any]:
            if isinstance(self._backend, LatencyRoutedChatBackend):
                return await self._backend.answer(
                    prompt=quality_prompt,
                    view_context=quality_context,
                    history=[],
                    preferred_model=str(draft_reply.get("model") or preferred_model or "") or None,
                )
            return await self._backend.answer(
                prompt=quality_prompt,
                view_context=quality_context,
                history=[],
            )

        with (
            with_correlation(metering_correlation_id(principal_id, session_id)),
            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
        ):
            quality = await await_with_interrupt(
                review_korean_narrator_answer(
                    answer=provisional_answer,
                    view_context=view_context,
                    locale=response_locale,
                    invoke=invoke_quality,
                ),
                active_turn=active_turn,
            )
        verification = verify_quality_result(
            quality,
            view_context,
            locale=_response_locale(clean_prompt, view_context),
        )
        return (
            {
                **draft_reply,
                "answer": verification.answer,
                "answer_quality": quality.to_dict(),
            },
            verification,
            history_metadata,
        )


def response_completion_dependencies() -> ResponseCompletionDependencies:
    """Return the explicit terminal projection and persistence dependency bundle."""

    return ResponseCompletionDependencies(
        monotonic=time.monotonic,
        now_utc=lambda: datetime.now(tz=UTC),
        planning_metadata=planning_metadata,
        delegation_summary=_delegation_summary,
        web_search_summary=_web_search_summary,
        public_intent_graph_evidence=public_intent_graph_evidence,
        assurance_policy_summary=assurance_policy_summary,
        response_incident_candidates=response_incident_candidates,
        response_resource_context=response_resource_context,
        response_resource_result_context=response_resource_result_context,
        response_source_failure_context=response_source_failure_context,
        response_llm_usage_analysis_context=response_llm_usage_analysis_context,
        response_llm_usage_chart_artifact=response_llm_usage_chart_artifact,
        response_presentation_artifact=response_presentation_artifact,
        response_evidence_freshness_context=response_evidence_freshness_context,
        extract_grounded_code=extract_grounded_code,
        append_assistant_turn=append_assistant_turn,
        replay_metadata=replay_metadata,
        turn_metadata=turn_metadata,
        post_turn_review_submission=PostTurnReviewSubmission,
        explicit_corrections=explicit_corrections,
    )


__all__ = [
    "GeneratedJsonTurn",
    "JsonTurnGenerator",
    "response_completion_dependencies",
]
