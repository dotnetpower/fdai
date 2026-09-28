"""Two-phase anchor binding reads exact identities before compilation."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
    bind_anchors,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    fixture_anchors,
    plan_verifier,
    production_manifest,
    span,
)


def _form(utterance: str, anchor: str, form: str = "name") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": form, "domain": "instance", "span": span(utterance, anchor)}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(utterance, "depend on"),
                },
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }


@pytest.mark.parametrize(
    ("text", "form"),
    (("sql-app", "name"), ("sql-app", "identifier"), ("sql-1", "identifier"), ("sql-1", "name")),
)
async def test_a_name_or_identifier_binds_the_same_exact_object(text: str, form: str) -> None:
    utterance = f"Which resources depend on {text}?"

    receipt = await fixture_anchors(admitted(_form(utterance, text, form), utterance))

    (binding,) = receipt.bindings
    assert (binding.outcome, binding.object_id) == (AnchorOutcome.BOUND, "sql-1")
    assert binding.source_generation == "fixture-generation"


async def test_an_absent_anchor_clarifies_instead_of_reading_text() -> None:
    utterance = "Which resources depend on sql-missing?"
    admission = admitted(_form(utterance, "sql-missing"), utterance)

    receipt = await fixture_anchors(admission)
    goal = _compile(admission, utterance, receipt).goals[0]

    assert receipt.bindings[0].outcome is AnchorOutcome.ABSENT
    assert goal.status is GoalStatus.CLARIFY
    assert goal.reasons == ("anchor_not_found:m1",)


@pytest.mark.parametrize(
    ("binding", "status", "reason"),
    (
        (
            AnchorBinding("m1", AnchorOutcome.AMBIGUOUS, candidates=("a", "b")),
            GoalStatus.CLARIFY,
            "anchor_ambiguous:m1",
        ),
        (
            AnchorBinding("m1", AnchorOutcome.INCOMPLETE),
            GoalStatus.UNSUPPORTED,
            "anchor_resolution_incomplete",
        ),
        (
            AnchorBinding("m1", AnchorOutcome.UNAVAILABLE),
            GoalStatus.UNSUPPORTED,
            "anchor_binding_unavailable",
        ),
    ),
)
def test_unbound_anchors_never_compile_a_read(
    binding: AnchorBinding, status: GoalStatus, reason: str
) -> None:
    utterance = "Which resources depend on sql-app?"
    admission = admitted(_form(utterance, "sql-app"), utterance)

    goal = _compile(admission, utterance, AnchorBindingReceipt((binding,))).goals[0]

    assert goal.status is status
    assert goal.reasons == (reason,)
    assert goal.batches == ()


async def test_without_a_resolver_every_anchor_is_unavailable() -> None:
    utterance = "Which resources depend on sql-app?"

    receipt = await bind_anchors(admitted(_form(utterance, "sql-app"), utterance), None)

    assert [item.outcome for item in receipt.bindings] == [AnchorOutcome.UNAVAILABLE]


def _compile(admission: Any, utterance: str, anchors: AnchorBindingReceipt) -> Any:
    return compile_question_form(
        admission,
        concepts=concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors,
    )
