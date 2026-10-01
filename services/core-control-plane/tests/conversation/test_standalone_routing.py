"""A standalone question routes as standalone, however long the conversation is."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.conversation_preflight_boundary import without_unbound_thread
from fdai.core.conversation.conversation_preflight_contracts import (
    ContextDependency,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    GeneralKnowledgeSignal,
    OperationalPreflightFamily,
    OperationalSignal,
    SocialAct,
)
from fdai.core.conversation.conversation_preflight_family_validation import (
    preflight_operational_judgment,
)
from fdai.core.conversation.semantic_planning_preflight import preflight_descriptor_intent
from fdai.core.conversation.semantic_type_grounding import type_selection_plan, with_grounded_types
from fdai_service_contracts.ontology_query import content_digest

from tests.conversation.semantic_reasoning_support import production_manifest

DIGEST = "sha256:" + "a" * 64
_UTTERANCE = "서비스 상태 알려줘"


def _proposal(**overrides: Any) -> ConversationPreflightProposal:
    fields: dict[str, Any] = {
        "social_act": SocialAct.NONE,
        "operational_signal": OperationalSignal.EXPLICIT,
        "context_dependency": ContextDependency.ACTIVE_THREAD,
        "operational_family": OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH,
        "operational_targets": (),
        "operational_facets": ("service_health",),
        "confidence": 0.99,
    }
    fields.update(overrides)
    return ConversationPreflightProposal(**fields)


def _result(proposal: ConversationPreflightProposal) -> ConversationPreflightResult:
    return ConversationPreflightResult(
        proposal=proposal,
        attempted=True,
        input_digest=content_digest({"utterance": _UTTERANCE}),
        proposal_digest=content_digest(proposal.model_dump(mode="json")),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )


@pytest.mark.parametrize("guess", [ContextDependency.ACTIVE_THREAD, ContextDependency.AMBIGUOUS])
def test_a_guessed_thread_never_narrows_an_explicit_standalone_question(
    guess: ContextDependency,
) -> None:
    guessed = _proposal(context_dependency=guess)
    standalone = without_unbound_thread(guessed)

    assert standalone.context_dependency is ContextDependency.NONE
    # Unnormalized, the reviewed family is rejected as context dependent.
    assert preflight_operational_judgment(_result(guessed), utterance=_UTTERANCE) is None
    judgment = preflight_operational_judgment(_result(standalone), utterance=_UTTERANCE)
    assert judgment is not None
    assert judgment.primary_intent == "query.subscription_service_health"
    assert preflight_descriptor_intent(_result(standalone)) == "query.subscription_service_health"


@pytest.mark.parametrize(
    "overrides",
    [
        # A contextual follow-up keeps its route, which reads the thread as before.
        {
            "operational_signal": OperationalSignal.CONTEXTUAL,
            "operational_family": OperationalPreflightFamily.NONE,
            "operational_facets": (),
        },
        # Social continuity and pending decisions are not guesses about a reference.
        {
            "social_act": SocialAct.THANKS,
            "operational_signal": OperationalSignal.NONE,
            "context_dependency": ContextDependency.SOCIAL_CONTINUITY,
            "operational_family": OperationalPreflightFamily.NONE,
            "operational_facets": (),
        },
        {"context_dependency": ContextDependency.PENDING_DECISION},
    ],
)
def test_follow_ups_and_typed_dependencies_keep_their_route(overrides: dict[str, Any]) -> None:
    proposal = _proposal(**overrides)

    assert without_unbound_thread(proposal) == proposal


def test_a_general_question_without_a_drafted_answer_keeps_its_valid_route() -> None:
    proposal = _proposal(
        operational_signal=OperationalSignal.NONE,
        operational_family=OperationalPreflightFamily.NONE,
        operational_facets=(),
        knowledge_signal=GeneralKnowledgeSignal.EXPLICIT,
    )

    # Reading it as standalone would need a drafted general answer, so it stays as is.
    assert without_unbound_thread(proposal) == proposal


def test_an_object_type_word_can_ground_as_its_object_type_not_a_resource_subtype() -> None:
    descriptors = production_manifest().descriptors
    plan = type_selection_plan(("인시던트",), descriptors, max_shard_bytes=12 * 1024)

    assert plan is not None
    presented = {
        candidate.id: candidate.values
        for request in plan.requests
        for candidate in request.shard.candidates
    }
    assert presented["object:Incident"] == ("Incident",)
    assert "object:Resource" not in presented
    grounded = with_grounded_types(descriptors, {"인시던트": ("Incident",)})
    resource = next(item for item in grounded if item.get("name") == "Resource")
    assert not any(
        str(group["id"]).startswith("turn-grounded:")
        for group in resource["properties"]["type"].get("value_groups") or ()
    )
