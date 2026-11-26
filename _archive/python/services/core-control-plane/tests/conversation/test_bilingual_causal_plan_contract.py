"""Annotated bilingual meaning compiles identically; this is not model-language qualification."""

from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_investigation import (
    InvestigationIntentProposal,
    verify_investigation_intent,
)
from fdai.core.conversation.semantic_investigation_planning import compile_investigation_plan
from fdai_service_contracts.ontology_query import QueryNodeKind

from tests.conversation.test_semantic_investigation_planning import (
    METRICS,
    _manifest,
    _span,
    _verified_intent,
    _verifier,
    _windows,
)


@pytest.mark.parametrize(
    ("question", "symptom", "time_cue", "cause_cue"),
    [
        ("Why did service-example suddenly become slow?", "slow", "suddenly", "Why"),
        ("service-example이 갑자기 왜 느려졌나요?", "느려졌나요", "갑자기", "왜"),
    ],
)
def test_annotated_bilingual_investigations_preserve_direction_time_and_competitors(
    question,
    symptom,
    time_cue,
    cause_cue,
):
    # Both fixtures provide independently annotated typed meaning. Code validates
    # exact spans; it does not infer their meaning from language.
    raw = _verified_intent().model_dump(
        mode="json",
        include=set(InvestigationIntentProposal.model_fields),
    )
    raw["entities"][0]["span"] = _span(question, "service-example")
    raw["symptom_measures"][0]["span"] = _span(question, symptom)
    raw["temporal_cues"][0]["span"] = _span(question, time_cue)
    raw["relationship_intents"][0]["span"] = _span(question, cause_cue)
    for hypothesis in raw["hypotheses"]:
        hypothesis["span"] = _span(question, cause_cue)
    intent = verify_investigation_intent(
        InvestigationIntentProposal.model_validate(raw),
        utterance=question,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )
    windows = _windows()
    plan = compile_investigation_plan(
        intent,
        manifest=_manifest(),
        verifier=_verifier(),
        windows=windows,
        purpose="operations-review",
    )
    assert plan.execution_authority is False
    target = plan.nodes[0].arguments["definition"]
    assert target["predicates"][0]["equals"] == "service-example"
    traversal = next(node for node in plan.nodes if node.kind is QueryNodeKind.TYPED_PATH)
    assert all(step["direction"] == "outgoing" for step in traversal.arguments["steps"])
    joins = [node for node in plan.nodes if node.kind is QueryNodeKind.EVIDENCE_JOIN]
    assert len(joins) == 2
    for join in joins:
        assert join.arguments["feature_cutoff"] == windows.current_end.isoformat()
        assert join.arguments["effect_direction"] == "increase"
        assert len(join.arguments["competing_explanations"]) == 1
