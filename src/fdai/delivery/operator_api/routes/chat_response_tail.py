"""Finalize a verified JSON chat response and persist its assistant turn."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from starlette.responses import JSONResponse


@dataclass(frozen=True)
class ChatResponseTailContext:
    """Request-local state required after chat generation and verification."""

    started: float
    reply: Mapping[str, Any]
    view_context: dict[str, Any]
    verification: Any
    answer_plan: Any
    planning_task: Any
    user_id: str
    session_id: str
    request_id: str
    clean_prompt: str
    history_metadata: dict[str, Any]
    response_locale: str | None
    resource_context: Any
    freshness_context: Any
    conversation_history_store: Any | None
    user_context_ontology_projector: Any | None
    post_turn_review_submitter: Any | None
    operator_turn: Any | None

    @classmethod
    def from_handler_locals(
        cls,
        values: Mapping[str, Any],
        *,
        post_turn_review_submitter: Any | None,
    ) -> ChatResponseTailContext:
        """Capture the completed handler state without moving request coordination here."""

        return cls(
            started=cast(float, values["started"]),
            reply=cast(Mapping[str, Any], values["reply"]),
            view_context=cast(dict[str, Any], values["view_context"]),
            verification=values["verification"],
            answer_plan=values["answer_plan"],
            planning_task=values["planning_task"],
            user_id=cast(str, values["user_id"]),
            session_id=cast(str, values["session_id"]),
            request_id=cast(str, values["request_id"]),
            clean_prompt=cast(str, values["clean_prompt"]),
            history_metadata=cast(dict[str, Any], values["history_metadata"]),
            response_locale=cast(str | None, values["response_locale"]),
            resource_context=values["resource_context"],
            freshness_context=values["freshness_context"],
            conversation_history_store=values["conversation_history_store"],
            user_context_ontology_projector=values["user_context_ontology_projector"],
            post_turn_review_submitter=post_turn_review_submitter,
            operator_turn=values["operator_turn"],
        )


@dataclass(frozen=True)
class ChatResponseTailDependencies:
    """Call-time dependencies that keep the ``chat`` compatibility patch surface intact."""

    monotonic: Callable[[], float]
    now_utc: Callable[[], datetime]
    planning_metadata: Callable[..., Any]
    delegation_summary: Callable[..., Any]
    web_search_summary: Callable[..., Any]
    public_intent_graph_evidence: Callable[..., Any]
    assurance_policy_summary: Callable[..., Any]
    response_incident_candidates: Callable[..., Any]
    response_resource_context: Callable[..., Any]
    response_resource_result_context: Callable[..., Any]
    response_source_failure_context: Callable[..., Any]
    response_llm_usage_analysis_context: Callable[..., Any]
    response_llm_usage_chart_artifact: Callable[..., Any]
    response_presentation_artifact: Callable[..., Any]
    response_evidence_freshness_context: Callable[..., Any]
    extract_grounded_code: Callable[..., Any]
    append_assistant_turn: Callable[..., Any]
    replay_metadata: Callable[..., Any]
    turn_metadata: Callable[..., Any]
    post_turn_review_submission: Callable[..., Any]
    explicit_corrections: Callable[..., Any]
    json_response: Callable[..., Any]

    @classmethod
    def from_chat_namespace(cls, namespace: Mapping[str, Any]) -> ChatResponseTailDependencies:
        """Resolve current globals so monkeypatches remain effective for each request."""

        datetime_type = namespace["datetime"]
        utc = namespace["UTC"]
        return cls(
            monotonic=_dependency(namespace["time"].monotonic, "time.monotonic"),
            now_utc=lambda: datetime_type.now(tz=utc),
            planning_metadata=_dependency(namespace["planning_metadata"], "planning_metadata"),
            delegation_summary=_dependency(namespace["_delegation_summary"], "_delegation_summary"),
            web_search_summary=_dependency(namespace["_web_search_summary"], "_web_search_summary"),
            public_intent_graph_evidence=_dependency(
                namespace["public_intent_graph_evidence"], "public_intent_graph_evidence"
            ),
            assurance_policy_summary=_dependency(
                namespace["assurance_policy_summary"], "assurance_policy_summary"
            ),
            response_incident_candidates=_dependency(
                namespace["response_incident_candidates"], "response_incident_candidates"
            ),
            response_resource_context=_dependency(
                namespace["response_resource_context"], "response_resource_context"
            ),
            response_resource_result_context=_dependency(
                namespace["response_resource_result_context"],
                "response_resource_result_context",
            ),
            response_source_failure_context=_dependency(
                namespace["response_source_failure_context"], "response_source_failure_context"
            ),
            response_llm_usage_analysis_context=_dependency(
                namespace["response_llm_usage_analysis_context"],
                "response_llm_usage_analysis_context",
            ),
            response_llm_usage_chart_artifact=_dependency(
                namespace["response_llm_usage_chart_artifact"],
                "response_llm_usage_chart_artifact",
            ),
            response_presentation_artifact=_dependency(
                namespace["response_presentation_artifact"], "response_presentation_artifact"
            ),
            response_evidence_freshness_context=_dependency(
                namespace["response_evidence_freshness_context"],
                "response_evidence_freshness_context",
            ),
            extract_grounded_code=_dependency(
                namespace["extract_grounded_code"], "extract_grounded_code"
            ),
            append_assistant_turn=_dependency(
                namespace["append_assistant_turn"], "append_assistant_turn"
            ),
            replay_metadata=_dependency(namespace["replay_metadata"], "replay_metadata"),
            turn_metadata=_dependency(namespace["_turn_metadata"], "_turn_metadata"),
            post_turn_review_submission=_dependency(
                namespace["PostTurnReviewSubmission"], "PostTurnReviewSubmission"
            ),
            explicit_corrections=_dependency(
                namespace["explicit_corrections"], "explicit_corrections"
            ),
            json_response=_dependency(namespace["JSONResponse"], "JSONResponse"),
        )


def _dependency(value: Any, name: str) -> Callable[..., Any]:
    if not callable(value):
        raise TypeError(f"chat response dependency {name} MUST be callable")
    return cast(Callable[..., Any], value)


async def finalize_chat_response(
    context: ChatResponseTailContext,
    dependencies: ChatResponseTailDependencies,
) -> JSONResponse:
    """Enrich, persist, submit review, and return one verified terminal payload."""

    latency_ms = int((dependencies.monotonic() - context.started) * 1000)
    answer_planning = await dependencies.planning_metadata(context.planning_task)
    enriched: dict[str, Any] = dict(context.reply)
    enriched.setdefault("source", None)
    enriched["delegation"] = dependencies.delegation_summary(context.view_context)
    enriched["web_search"] = dependencies.web_search_summary(context.view_context)
    enriched["latency_ms"] = latency_ms
    enriched["history_context"] = context.history_metadata
    enriched["answer_plan"] = context.answer_plan.to_dict()
    if isinstance(context.view_context.get("_intent_graph"), Mapping):
        enriched["intent_graph"] = dict(context.view_context["_intent_graph"])
    if isinstance(context.view_context.get("_intent_graph_evidence"), Mapping):
        graph_evidence = dependencies.public_intent_graph_evidence(
            context.view_context["_intent_graph_evidence"]
        )
        enriched["intent_graph_evidence"] = graph_evidence
        enriched["evidence_mode"] = graph_evidence.get("evidence_mode")
    policy_summary = dependencies.assurance_policy_summary(context.view_context)
    if policy_summary is not None:
        enriched["conversation_policy"] = policy_summary
    enriched["answer_planning"] = answer_planning
    incident_candidates = dependencies.response_incident_candidates(
        context.view_context,
        verification=context.verification,
        locale=context.response_locale,
    )
    if incident_candidates is not None:
        enriched["incident_candidates"] = incident_candidates
    selected_resource = dependencies.response_resource_context(
        context.view_context,
        context.resource_context,
    )
    if selected_resource is not None:
        enriched["resource_context"] = selected_resource
    resource_result_context = dependencies.response_resource_result_context(
        context.view_context,
        verification_status=context.verification.status,
    )
    if resource_result_context is not None:
        enriched["resource_result_context"] = resource_result_context
    source_failure_context = dependencies.response_source_failure_context(
        context.view_context,
        verification_status=context.verification.status,
    )
    if source_failure_context is not None:
        enriched["source_failure_context"] = source_failure_context
    analysis_context = dependencies.response_llm_usage_analysis_context(
        context.view_context,
        verification_status=context.verification.status,
    )
    if analysis_context is not None:
        enriched["analysis_context"] = analysis_context
    chart_artifact = dependencies.response_llm_usage_chart_artifact(
        context.view_context,
        verification_status=context.verification.status,
        answer_format=context.answer_plan.format.value,
        locale=context.response_locale,
    )
    if chart_artifact is not None:
        enriched["chart_artifact"] = chart_artifact
    presentation_artifact = dependencies.response_presentation_artifact(
        context.view_context,
        answer_plan=context.answer_plan,
        verification_status=context.verification.status,
        evidence_refs=context.verification.evidence_refs,
        locale=context.response_locale,
    )
    if presentation_artifact is not None:
        enriched["presentation_artifact"] = presentation_artifact
    selected_freshness = dependencies.response_evidence_freshness_context(
        context.view_context,
        context.freshness_context,
    )
    if selected_freshness is not None:
        enriched["evidence_freshness_context"] = selected_freshness.to_dict()
    enriched["code_artifacts"] = [
        artifact.to_dict()
        for artifact in dependencies.extract_grounded_code(context.verification.answer)
    ]
    if context.conversation_history_store is not None:
        assistant_turn = await dependencies.append_assistant_turn(
            store=context.conversation_history_store,
            principal_id=context.user_id,
            conversation_id=context.session_id,
            request_id=context.request_id,
            content=context.verification.answer,
            recorded_at=dependencies.now_utc(),
            metadata=dependencies.replay_metadata(
                model=str(context.reply.get("model") or "unknown"),
                payload=enriched,
                additional=dependencies.turn_metadata(
                    model=str(context.reply.get("model") or "unknown"),
                    view_context=context.view_context,
                    answer_planning=answer_planning,
                )
                | context.history_metadata,
            ),
            ontology_projector=context.user_context_ontology_projector,
        )
        if context.post_turn_review_submitter is not None and context.operator_turn is not None:
            context.post_turn_review_submitter.submit_nowait(
                operator_turn=context.operator_turn,
                assistant_turn=assistant_turn,
                submission=dependencies.post_turn_review_submission(
                    validation_outcomes=(context.verification.status,),
                    evidence_refs=context.verification.evidence_refs,
                    explicit_corrections=dependencies.explicit_corrections(context.clean_prompt),
                ),
            )
    response = dependencies.json_response(enriched)
    return cast(JSONResponse, response)
