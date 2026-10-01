from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus
from fdai.core.conversation.semantic_reasoning_form import RelationSense

from tests.conversation.semantic_reasoning_support import span
from tests.conversation.test_semantic_reasoning_compiler import _compile, _relation_form

_UTTERANCE = "What should FDAI read about anchor-a?"


@pytest.mark.parametrize(
    ("operation", "reason"),
    (
        ("rank", "rank_measure_unreviewed"),
        ("aggregate", "aggregate_measure_unreviewed"),
        ("compare_windows", "compare_windows_requires_two_typed_windows"),
        ("compare_entities", "compare_entities_requires_two_bound_anchors"),
        ("diff_versions", "version_history_unavailable"),
        ("verify_evidence", "link_evidence_allowlist_unavailable"),
        ("diagnose", "diagnose_recipe_unavailable"),
    ),
)
def test_remaining_operator_rows_keep_exact_prerequisite_reason(
    operation: str, reason: str
) -> None:
    compilation = _compile(_UTTERANCE, _form(operation))
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == (reason,)


def test_path_operator_keeps_path_grammar_prerequisite_reason() -> None:
    utterance = "What path connects anchor-a?"
    compilation = _compile(
        utterance,
        _relation_form(
            utterance,
            anchor="anchor-a",
            sense=RelationSense.DEPENDENCY.value,
            position="source",
            cue="connects",
            operation="path",
        ),
    )
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("path_grammar_unavailable",)


def _form(operation: str) -> dict[str, object]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "name",
                "domain": "instance",
                "span": span(_UTTERANCE, "anchor-a"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "state",
                "span": span(_UTTERANCE, "read"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "state", "mention": "m2"},
                "cue": span(_UTTERANCE, "What"),
                "confidence": 0.91,
            }
        ],
    }
