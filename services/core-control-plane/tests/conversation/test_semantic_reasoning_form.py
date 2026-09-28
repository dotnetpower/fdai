"""Question-form contracts, admission, and relation-side selection."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_admission import (
    AdmissionDisposition,
    SpanAccounting,
    admit_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import (
    MAX_FORM_GOALS,
    RelationReach,
    RelationScope,
    RelationSense,
    SemanticQuestionForm,
    SubjectPosition,
)
from fdai.core.conversation.semantic_reasoning_relations import (
    SENSE_TRAITS,
    select_relation_sides,
)
from pydantic import ValidationError

from tests.conversation.semantic_reasoning_support import production_manifest, span

_UTTERANCE = "Which resources depend on aks-prod-01?"


def _traverse(**goal: Any) -> dict[str, Any]:
    base = {
        "id": "g1",
        "level": "instance",
        "operation": "traverse",
        "subject": "m1",
        "subject_scope": "anchor",
        "relation": {
            "sense": "dependency",
            "anchor_role": "dependency",
            "result_role": "dependent",
            "cue": span(_UTTERANCE, "depend on"),
        },
        "cue": span(_UTTERANCE, "Which resources"),
        "confidence": 0.93,
    }
    base.update(goal)
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "name",
                "domain": "instance",
                "span": span(_UTTERANCE, "aks-prod-01"),
            }
        ],
        "goals": [base],
    }


def test_admitted_form_exposes_exact_mention_text() -> None:
    admission = admit_question_form(
        SemanticQuestionForm.model_validate(_traverse()), utterance=_UTTERANCE
    )

    assert admission.disposition is AdmissionDisposition.ADMITTED
    assert admission.mention_text == {"m1": "aks-prod-01"}
    assert admission.form.execution_authority is False


@pytest.mark.parametrize(
    ("update", "reason"),
    (
        ({"cue": {"start": 0, "end": 99}}, "goal_cue_span_invalid:g1"),
        ({"relation": None}, "relation_required:g1"),
        ({"level": "schema", "operation": "traverse"}, "schema_subject_domain:g1"),
        ({"operation": "lookup"}, "measure_required:g1"),
        ({"subject_scope": "goal_output"}, "goal_output_dependency_missing:g1"),
    ),
)
def test_inconsistent_forms_are_invalid(update: dict[str, Any], reason: str) -> None:
    admission = admit_question_form(
        SemanticQuestionForm.model_validate(_traverse(**update)), utterance=_UTTERANCE
    )

    assert admission.disposition is AdmissionDisposition.INVALID
    assert reason in admission.reasons


def test_whitespace_padded_span_is_not_an_exact_mention() -> None:
    form = _traverse()
    form["mentions"][0]["span"] = {"start": 25, "end": 37}

    admission = admit_question_form(SemanticQuestionForm.model_validate(form), utterance=_UTTERANCE)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert "mention_span_invalid:m1" in admission.reasons


def test_competing_readings_clarify_and_low_confidence_reviews() -> None:
    competing = _traverse()
    competing["alternatives"] = [
        {"goal": "g1", "atoms": [{"field": "relation.anchor_role", "value": "dependent"}]}
    ]
    clarify = admit_question_form(
        SemanticQuestionForm.model_validate(competing), utterance=_UTTERANCE
    )
    review = admit_question_form(
        SemanticQuestionForm.model_validate(_traverse(confidence=0.4)), utterance=_UTTERANCE
    )

    assert clarify.disposition is AdmissionDisposition.CLARIFY
    assert clarify.reasons == ("competing_reading:g1",)
    assert review.disposition is AdmissionDisposition.REVIEW
    assert review.reasons == ("low_confidence:g1",)


def test_remaining_goals_request_a_continuation_pass() -> None:
    form = _traverse()
    form["remaining_goals"] = True

    admission = admit_question_form(SemanticQuestionForm.model_validate(form), utterance=_UTTERANCE)

    assert admission.disposition is AdmissionDisposition.ADMITTED
    assert admission.needs_continuation is True


@pytest.mark.parametrize(
    "mutate",
    (
        lambda form: form["goals"].append(dict(form["goals"][0])),
        lambda form: form["goals"][0].update(subject="m9"),
        lambda form: form["goals"][0].update(depends_on=["g2"]),
        lambda form: form.update(execution_authority=True),
        lambda form: form["goals"][0].update(operation="query.resource_current_state"),
    ),
)
def test_form_contract_rejects_unclosed_or_dangling_fields(mutate: Any) -> None:
    form = _traverse()
    mutate(form)

    with pytest.raises(ValidationError):
        SemanticQuestionForm.model_validate(form)


def test_form_bounds_goals_and_requires_typed_time_values() -> None:
    form = _traverse()
    form["goals"] = [
        {**form["goals"][0], "id": f"g{index}"} for index in range(1, MAX_FORM_GOALS + 2)
    ]
    with pytest.raises(ValidationError):
        SemanticQuestionForm.model_validate(form)
    windowed = _traverse(time={"kind": "window"})
    with pytest.raises(ValidationError):
        SemanticQuestionForm.model_validate(windowed)


def test_every_relation_sense_has_a_reviewed_trait_decision() -> None:
    assert set(SENSE_TRAITS) == set(RelationSense)


@pytest.mark.parametrize(
    ("position", "expected"),
    (
        (SubjectPosition.TARGET, {("depends_on", "incoming")}),
        (SubjectPosition.SOURCE, {("depends_on", "outgoing")}),
        (SubjectPosition.EITHER, {("depends_on", "incoming"), ("depends_on", "outgoing")}),
    ),
)
def test_subject_position_selects_the_stored_side(
    position: SubjectPosition, expected: set[tuple[str, str]]
) -> None:
    selection = select_relation_sides(
        production_manifest().descriptors,
        anchor_type="Resource",
        sense=RelationSense.DEPENDENCY,
        scope=RelationScope.ONE_SENSE,
        position=position,
        reach=RelationReach.ONE_HOP,
    )

    assert {(side.link_type, side.direction) for side in selection.sides} == expected
    assert "emits_to" in selection.unmapped_link_types


def test_transitive_reach_keeps_only_self_composable_links() -> None:
    descriptors = production_manifest().descriptors
    containment = select_relation_sides(
        descriptors,
        anchor_type="Resource",
        sense=RelationSense.CONTAINMENT,
        scope=RelationScope.ONE_SENSE,
        position=SubjectPosition.SOURCE,
        reach=RelationReach.TRANSITIVE,
    )
    dependency = select_relation_sides(
        descriptors,
        anchor_type="Resource",
        sense=RelationSense.DEPENDENCY,
        scope=RelationScope.ONE_SENSE,
        position=SubjectPosition.TARGET,
        reach=RelationReach.TRANSITIVE,
    )

    assert [(side.link_type, side.max_depth) for side in containment.sides] == [("contains", 5)]
    assert dependency.sides == ()
    assert dependency.intransitive_link_types == ("depends_on",)


def test_all_kinds_reads_every_link_side_including_unmapped_links() -> None:
    selection = select_relation_sides(
        production_manifest().descriptors,
        anchor_type="Resource",
        sense=None,
        scope=RelationScope.ALL_KINDS,
        position=SubjectPosition.EITHER,
        reach=RelationReach.ONE_HOP,
    )
    names = {side.link_type for side in selection.sides}

    assert {"contains", "depends_on", "emits_to", "workload_runs_on"} <= names
    assert selection.unmapped_link_types == ()


@pytest.mark.parametrize(
    ("utterance", "text", "disposition"),
    (
        ("List VMs in rg-app-dev", "rg-app", AdmissionDisposition.INVALID),
        ("rg-app에 있는 VM", "rg-app", AdmissionDisposition.ADMITTED),
        ("List VMs in rg-app.", "rg-app", AdmissionDisposition.ADMITTED),
        ("List VMs in rg-app.dev", "rg-app", AdmissionDisposition.INVALID),
        ("List VMs in dev-rg-app", "rg-app", AdmissionDisposition.INVALID),
        ("Is (rg-app) healthy?", "rg-app", AdmissionDisposition.ADMITTED),
    ),
)
def test_an_instance_quote_cannot_cut_through_a_longer_identifier(
    utterance: str, text: str, disposition: AdmissionDisposition
) -> None:
    start = utterance.index(text)
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "name",
                "domain": "instance",
                "span": {"start": start, "end": start + len(text)},
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1"}],
                "cue": {"start": 0, "end": 1},
                "confidence": 0.9,
            }
        ],
    }

    admission = admit_question_form(
        SemanticQuestionForm.model_validate(form),
        utterance=utterance,
        accounting=SpanAccounting(required=False),
    )

    assert admission.disposition is disposition


def test_a_declared_restriction_hidden_under_a_wide_cue_still_clarifies() -> None:
    utterance = "List VMs in eastus"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            {"id": "m2", "form": "value", "domain": "region", "span": span(utterance, "eastus")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": span(utterance, "List VMs in eastus"),
                "confidence": 0.9,
            }
        ],
    }

    admission = admit_question_form(SemanticQuestionForm.model_validate(form), utterance=utterance)

    assert admission.disposition is AdmissionDisposition.CLARIFY
    assert admission.reasons == ("mention_unused:m2",)


def test_qualifier_chains_are_cited_regardless_of_mention_order() -> None:
    utterance = "vnet-a 서브넷의 VM 목록"
    mentions = [
        {
            "id": "m3",
            "form": "concept",
            "domain": "resource_type",
            "span": span(utterance, "VM"),
            "qualifier": {"mention": "m2", "sense": "containment"},
        },
        {
            "id": "m2",
            "form": "concept",
            "domain": "resource_type",
            "span": span(utterance, "서브넷"),
            "qualifier": {"mention": "m1", "sense": "containment"},
        },
        {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, "vnet-a")},
    ]
    goal = {
        "id": "g1",
        "level": "instance",
        "operation": "select",
        "subject": "m3",
        "subject_scope": "collection",
        "cue": span(utterance, "목록"),
        "confidence": 0.9,
    }
    forward = SemanticQuestionForm.model_validate({"mentions": mentions, "goals": [goal]})
    reverse = SemanticQuestionForm.model_validate({"mentions": mentions[::-1], "goals": [goal]})

    assert forward.cited_mentions() == reverse.cited_mentions() == {"m1", "m2", "m3"}
