"""Question-form contracts, admission, and relation-side selection."""

from __future__ import annotations

import json
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
        (
            SubjectPosition.TARGET,
            {("depends_on", "incoming"), ("kubernetes_owned_by", "incoming")},
        ),
        (
            SubjectPosition.SOURCE,
            {("depends_on", "outgoing"), ("kubernetes_owned_by", "outgoing")},
        ),
        (
            SubjectPosition.EITHER,
            {
                ("depends_on", "incoming"),
                ("depends_on", "outgoing"),
                ("kubernetes_owned_by", "incoming"),
                ("kubernetes_owned_by", "outgoing"),
            },
        ),
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
    assert selection.unmapped_link_types == ()


def test_every_resource_link_type_has_a_reviewed_semantic_trait() -> None:
    unreviewed = [
        descriptor["name"]
        for descriptor in production_manifest().descriptors
        if descriptor.get("kind") == "link"
        and "Resource" in {descriptor.get("from_type"), descriptor.get("to_type")}
        and not descriptor.get("semantic_traits")
    ]
    assert unreviewed == []


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
    assert dependency.intransitive_link_types == ("depends_on", "kubernetes_owned_by")


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

    parsed = SemanticQuestionForm.model_validate(form)
    unaccounted = admit_question_form(
        parsed, utterance=utterance, accounting=SpanAccounting(required=False)
    )
    accounted = admit_question_form(parsed, utterance=utterance)

    # The wide cue accounts for every word, and the unused restriction still clarifies.
    for admission in (unaccounted, accounted):
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


def _admit(raw: dict[str, Any], utterance: str) -> Any:
    return admit_question_form(
        SemanticQuestionForm.model_validate(raw),
        utterance=utterance,
        accounting=SpanAccounting(required=False),
    )


def test_two_mentions_never_share_words() -> None:
    utterance = "What is in rg-app-dev?"
    raw = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "What is in rg-app-dev"),
            },
            {
                "id": "m2",
                "form": "name",
                "domain": "instance",
                "span": span(utterance, "rg-app-dev"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "relation": {
                    "sense": "containment",
                    "anchor": "m2",
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": span(utterance, "is in"),
                },
                "cue": span(utterance, "What"),
                "confidence": 0.9,
            }
        ],
    }

    admission = _admit(raw, utterance)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert "mention_overlap:m2" in admission.reasons


def _qualified_count(utterance: str, kind: str, qualifier_domain: str, text: str) -> Any:
    return _admit(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(utterance, kind),
                    "qualifier": {"mention": "m2", "sense": "containment"},
                },
                {
                    "id": "m2",
                    "form": "value" if qualifier_domain == "state" else "name",
                    "domain": qualifier_domain,
                    "span": span(utterance, text),
                },
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "count",
                    "subject": "m1",
                    "subject_scope": "collection",
                    "measure": {"kind": "count"},
                    "cue": span(utterance, "How many"),
                    "confidence": 0.9,
                }
            ],
        },
        utterance,
    )


@pytest.mark.parametrize(
    ("utterance", "kind", "domain", "text"),
    (
        ("How many running VMs are there?", "VMs", "state", "running"),
        ("How many VMs in rg-app are there?", "VMs", "instance", "rg-app"),
    ),
)
def test_a_qualifier_only_places_a_named_resource_in_another(
    utterance: str, kind: str, domain: str, text: str
) -> None:
    admission = _qualified_count(utterance, kind, domain, text)

    # A kind or a state of the results is a filter and a container is the goal's relation;
    # as a qualifier it reaches no builder, so admission asks for the one repair instead.
    assert admission.disposition is AdmissionDisposition.INVALID
    assert "qualifier_not_instance:m1" in admission.reasons


def test_a_named_resource_qualified_by_its_container_is_admitted() -> None:
    utterance = "What is the state of aks-prod-01 in rg-app?"
    admission = _admit(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "name",
                    "domain": "instance",
                    "span": span(utterance, "aks-prod-01"),
                    "qualifier": {"mention": "m2", "sense": "containment"},
                },
                {
                    "id": "m2",
                    "form": "name",
                    "domain": "instance",
                    "span": span(utterance, "rg-app"),
                },
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "lookup",
                    "subject": "m1",
                    "subject_scope": "anchor",
                    "measure": {"kind": "state"},
                    "cue": span(utterance, "What is"),
                    "confidence": 0.9,
                }
            ],
        },
        utterance,
    )

    assert not any(reason.startswith("qualifier_not_instance") for reason in admission.reasons)


def test_a_group_is_the_scope_and_a_relation_anchor_only_as_one_membership() -> None:
    utterance = "rg-app의 모든 리소스를 보여줘"
    raw = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, "rg-app")},
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "리소스를"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1"}],
                "relation": {
                    "sense": "containment",
                    "anchor": "m1",
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": span(utterance, "의"),
                },
                "cue": span(utterance, "보여줘"),
                "confidence": 0.9,
            }
        ],
    }
    scoped = {**raw, "goals": [{**raw["goals"][0], "relation": None}]}
    closure = json.loads(json.dumps(raw))
    closure["goals"][0]["relation"]["reach"] = "transitive"
    depends = json.loads(json.dumps(raw))
    depends["goals"][0]["relation"].update(
        sense="dependency", anchor_role="dependency", result_role="dependent"
    )

    assert _admit(scoped, utterance).disposition is AdmissionDisposition.ADMITTED
    # One phrase such as rg-app의 read both as the scope and as a containment from the same
    # group names one membership; the compiler reads the scope's whole membership.
    assert "scope_anchor_conflict:g1" not in _admit(raw, utterance).reasons
    assert "scope_anchor_conflict:g1" not in _admit(closure, utterance).reasons
    # Another sense from the scope group asks for something else, so it stays a conflict.
    assert "scope_anchor_conflict:g1" in _admit(depends, utterance).reasons


def test_a_reciprocal_link_is_read_on_both_sides_whatever_direction_is_stated() -> None:
    descriptors = production_manifest().descriptors

    for position in (SubjectPosition.SOURCE, SubjectPosition.TARGET, SubjectPosition.EITHER):
        selection = select_relation_sides(
            descriptors,
            anchor_type="Resource",
            sense=RelationSense.CONNECTIVITY,
            scope=RelationScope.ONE_SENSE,
            position=position,
            reach=RelationReach.ONE_HOP,
        )
        peering = {(side.link_type, side.direction) for side in selection.sides}
        assert {("peered_with", "outgoing"), ("peered_with", "incoming")} <= peering
