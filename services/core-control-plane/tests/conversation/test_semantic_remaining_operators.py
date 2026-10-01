from __future__ import annotations

import pytest
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain, RelationSense
from fdai_core_service.semantic_verified_rows import with_stated_notices
from fdai_service_contracts.ontology_query import QueryNodeKind

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    plan_verifier,
    production_manifest,
    span,
    synthetic_anchors,
)
from tests.conversation.test_semantic_reasoning_compiler import _compile, _relation_form

_UTTERANCE = "What should FDAI read about anchor-a and anchor-b?"


@pytest.mark.parametrize(
    ("operation", "reason"),
    (
        ("aggregate", "aggregate_measure_unreviewed"),
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


def test_rank_keeps_unreviewed_measure_reason_after_order_is_bound() -> None:
    compilation = _compile(
        _UTTERANCE,
        _form(
            "rank",
            measure={
                "kind": "state",
                "mention": "m2",
                "order": {
                    "direction": "descending",
                    "limit": 5,
                    "cue": span(_UTTERANCE, "read"),
                },
            },
        ),
    )
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("rank_measure_unreviewed",)


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


def test_compare_windows_compiles_two_metric_windows_and_comparison() -> None:
    utterance = "Compare CPU for anchor-a in two windows"
    compilation = _compile_form(
        utterance,
        {
            "mentions": [
                _mention("m1", "name", "instance", utterance, "anchor-a"),
                _mention("m2", "concept", "metric", utterance, "CPU"),
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "compare_windows",
                    "subject": "m1",
                    "subject_scope": "anchor",
                    "measure": {"kind": "metric", "mention": "m2"},
                    "time": {
                        "kind": "two_windows",
                        "windows": [
                            {"duration": {"amount": 5, "unit": "minute"}},
                            {"duration": {"amount": 5, "unit": "minute"}},
                        ],
                        "cue": span(utterance, "two windows"),
                    },
                    "cue": span(utterance, "Compare"),
                    "confidence": 0.91,
                }
            ],
        },
        concepts(("m2", MentionDomain.METRIC, ("resource.cpu.utilization_pct",))),
    )
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    assert [node.kind for node in batch.plan.nodes].count(QueryNodeKind.METRIC_SCOPE_SERIES) == 2
    assert batch.plan.output_node_ids == ("g1-comparison",)
    # The answer names both windows it compared, through a reviewed notice.
    assert goal.limitations == ("comparison_windows:300.300",)
    assert batch.frame.evidence_requirements == ("window.compared.300.300",)
    answer = with_stated_notices("## CPU\nrows", batch.frame.evidence_requirements, locale="en-US")
    assert "Compared windows: the last 5 minutes, and the 5 minutes just before it." in answer


def _form(operation: str, *, measure: dict[str, object] | None = None) -> dict[str, object]:
    form = {
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
                **({"counterpart": "m3"} if operation == "compare_entities" else {}),
                "subject_scope": "anchor",
                "measure": measure or {"kind": "state", "mention": "m2"},
                "cue": span(_UTTERANCE, "What"),
                "confidence": 0.91,
            }
        ],
    }
    if operation == "compare_entities":
        form["mentions"].append(  # type: ignore[index,union-attr]
            {
                "id": "m3",
                "form": "name",
                "domain": "instance",
                "span": span(_UTTERANCE, "anchor-b"),
            }
        )
    return form


def _compile_form(utterance: str, form: dict[str, object], receipt):
    admission = admitted(form, utterance)
    return compile_question_form(
        admission,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )


def _mention(mention_id: str, form: str, domain: str, utterance: str, text: str):
    return {"id": mention_id, "form": form, "domain": domain, "span": span(utterance, text)}
