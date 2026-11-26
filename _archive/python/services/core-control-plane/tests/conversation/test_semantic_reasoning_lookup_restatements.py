"""A lookup accepts the kind word and the asked state that restate its named subject."""

from __future__ import annotations

from typing import Any

from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    plan_verifier,
    production_manifest,
    span,
)

_UTTERANCE = "Is the AKS cluster aks-app-01 running right now?"


def _form(filters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(_UTTERANCE, "AKS cluster"),
            },
            {
                "id": "m2",
                "form": "name",
                "domain": "instance",
                "span": span(_UTTERANCE, "aks-app-01"),
            },
            {"id": "m3", "form": "value", "domain": "state", "span": span(_UTTERANCE, "running")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m2",
                "subject_scope": "anchor",
                "filters": filters,
                "measure": {"kind": "state", "mention": "m3"},
                "cue": span(_UTTERANCE, "Is"),
                "confidence": 0.9,
            }
        ],
    }


_RESTATING = [
    {"role": "type", "mention": "m1", "cue": span(_UTTERANCE, "the")},
    {"role": "state", "mention": "m3", "cue": span(_UTTERANCE, "running")},
]


def _compile(filters: list[dict[str, Any]], *, bound_type: str | None) -> Any:
    admission = admitted(_form(filters), _UTTERANCE)
    return compile_question_form(
        admission,
        concepts=concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("kubernetes-cluster",)),
            ("m3", MentionDomain.STATE, ("resource_state.running",)),
        ),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_UTTERANCE,
        anchors=AnchorBindingReceipt(
            (
                AnchorBinding(
                    "m2", AnchorOutcome.BOUND, object_id="object-m2", resource_type=bound_type
                ),
            )
        ),
    )


def test_the_kind_word_and_the_asked_state_do_not_block_a_state_lookup() -> None:
    goal = _compile(_RESTATING, bound_type="kubernetes-cluster").goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons


def test_a_kind_that_contradicts_the_bound_resource_asks_instead_of_answering() -> None:
    goal = _compile(_RESTATING, bound_type="virtual-machine").goals[0]

    assert goal.status is not GoalStatus.COMPILED
    assert "anchor_type_mismatch" in goal.reasons


def test_a_kind_that_cannot_be_checked_against_the_bound_resource_is_unsupported() -> None:
    goal = _compile(_RESTATING, bound_type=None).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("lookup_type_unverified",)


def test_a_filter_that_narrows_a_lookup_stays_unsupported() -> None:
    narrowing = [
        *_RESTATING,
        {"role": "name_fragment", "mention": "m2", "cue": span(_UTTERANCE, "aks-app-01")},
    ]
    admission = admitted(_form(narrowing), _UTTERANCE)
    assert admission.disposition.value == "admitted", admission.reasons
    goal = _compile(narrowing, bound_type="kubernetes-cluster").goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("filter_unsupported_for_operation:lookup",)
