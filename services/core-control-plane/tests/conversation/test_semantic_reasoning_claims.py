"""V-CLAIM rejects answers whose statements are not entailed by verified evidence."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_claims import (
    ComposedAnswer,
    GoalEvidence,
    GoalEvidenceStatus,
    verify_answer_claims,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable

_ROWS = (
    QueryRow.from_values(
        "kv-1",
        {"id": "kv-1", "object_type": "Resource", "properties": {"name": "kv-app"}},
    ),
    QueryRow.from_values(
        "sql-1",
        {"id": "sql-1", "object_type": "Resource", "properties": {"name": "sql-app"}},
    ),
)
_TEXT = "aks-prod-01 depends on kv-app and sql-app."


def _evidence(**updates: Any) -> GoalEvidence:
    values: dict[str, Any] = {
        "goal_id": "g1",
        "status": GoalEvidenceStatus.VERIFIED,
        "tables": {"g1-side-1": QueryTable(rows=_ROWS, complete=True)},
    }
    values.update(updates)
    return GoalEvidence(**values)


def _literal(text: str, needle: str, row: str) -> dict[str, Any]:
    start = text.index(needle)
    return {
        "span": {"start": start, "end": start + len(needle)},
        "value": needle,
        "ref": {"goal": "g1", "node": "g1-side-1", "row": row, "field": "properties.name"},
    }


def _answer(text: str = _TEXT, **claim: Any) -> ComposedAnswer:
    body: dict[str, Any] = {
        "id": "c1",
        "kind": "relation",
        "span": {"start": 0, "end": len(text)},
        "refs": [{"goal": "g1", "node": "g1-side-1"}],
        "rows": ["kv-1", "sql-1"],
    }
    if "literals" not in claim:
        body["literals"] = [
            _literal(text, "kv-app", "kv-1"),
            _literal(text, "sql-app", "sql-1"),
        ]
    body.update(claim)
    return ComposedAnswer.model_validate({"text": text, "claims": [body]})


def _verdict(answer: ComposedAnswer, *evidence: GoalEvidence) -> tuple[str, ...]:
    return verify_answer_claims(
        answer,
        evidence=evidence or (_evidence(),),
        known_identities=frozenset({"aks-prod-01"}),
    ).violations


def test_entailed_relation_answer_is_accepted() -> None:
    answer = _answer(
        literals=[
            _literal(_TEXT, "kv-app", "kv-1"),
            _literal(_TEXT, "sql-app", "sql-1"),
        ]
    )

    # The anchor name is a known identity, so it must be declared too.
    assert _verdict(answer) == ("undeclared_literal:0",)


def test_all_literals_declared_passes() -> None:
    text = "It depends on kv-app and sql-app."

    assert _verdict(_answer(text=text)) == ()


@pytest.mark.parametrize(
    ("text", "literal_update", "violation"),
    (
        (
            "It depends on kv-app and sql-app.",
            {"value": "kv-app-2"},
            "literal_text_mismatch:c1",
        ),
        (
            "It depends on kv-app and sql-app.",
            {
                "ref": {
                    "goal": "g1",
                    "node": "g1-side-1",
                    "row": "sql-1",
                    "field": "properties.name",
                }
            },
            "literal_value_mismatch:c1",
        ),
    ),
)
def test_literals_must_render_their_exact_evidence_cell(
    text: str, literal_update: dict[str, Any], violation: str
) -> None:
    literal = {**_literal(text, "kv-app", "kv-1"), **literal_update}
    answer = _answer(text=text, literals=[literal, _literal(text, "sql-app", "sql-1")])

    assert violation in _verdict(answer)


def test_invented_identity_and_unaccounted_rows_are_rejected() -> None:
    text = "It depends on kv-app and vm-extra-09."
    answer = _answer(text=text, literals=[_literal(text, "kv-app", "kv-1")], rows=["kv-1"])

    violations = _verdict(answer)

    assert f"undeclared_literal:{text.index('vm-extra-09')}" in violations
    assert "result_rows_unaccounted:g1:g1-side-1" in violations


def test_rendered_evidence_table_accounts_for_every_row() -> None:
    text = "It depends on the resources listed below."
    answer = _answer(text=text, literals=[], rows=[])

    rendered = _verdict(answer, _evidence(rendered_nodes=frozenset({"g1-side-1"})))
    hidden = _verdict(answer)

    assert rendered == ()
    assert hidden == ("result_rows_unaccounted:g1:g1-side-1",)


def test_counts_must_equal_the_authoritative_count_and_carry_their_quantifier() -> None:
    text = "There are 3 dependencies."
    count_ref = {"goal": "g1", "node": "g1-count", "row": "aggregate:x", "field": "value"}
    table = QueryTable(
        rows=(
            QueryRow.from_values("aggregate:x", {"group": {}, "operation": "count", "value": 2}),
        ),
        complete=True,
    )
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "count",
                    "span": {"start": 0, "end": len(text)},
                    "refs": [{"goal": "g1", "node": "g1-count"}],
                    "literals": [{"span": {"start": 10, "end": 11}, "value": 3, "ref": count_ref}],
                }
            ],
        }
    )
    evidence = GoalEvidence(
        goal_id="g1",
        status=GoalEvidenceStatus.UNKNOWN_INCOMPLETE,
        tables={"g1-count": table},
        authoritative_count=2,
    )

    violations = _verdict(answer, evidence)

    assert "literal_value_mismatch:c1" in violations
    assert "count_differs_from_authority:c1" in violations
    assert "count_quantifier_mismatch:c1" in violations


def test_negative_and_causal_claims_need_closed_population_and_causal_evidence() -> None:
    text = "Nothing depends on it, because it was restarted."
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "relation",
                    "span": {"start": 0, "end": 21},
                    "refs": [{"goal": "g1", "node": "g1-side-1"}],
                    "proposition": {"polarity": "deny"},
                    "rows": ["kv-1", "sql-1"],
                },
                {
                    "id": "c2",
                    "kind": "cause_hypothesis",
                    "span": {"start": 23, "end": len(text)},
                    "refs": [{"goal": "g1", "node": "g1-side-1"}],
                    "proposition": {"modality": "hypothesis"},
                },
            ],
        }
    )

    violations = _verdict(answer, _evidence(status=GoalEvidenceStatus.UNKNOWN_INCOMPLETE))

    assert "negative_claim_without_closed_population:c1" in violations
    assert "cause_without_causal_evidence:c2" in violations


def test_required_limitations_and_unavailable_goals_are_enforced() -> None:
    text = "It depends on kv-app and sql-app."
    answer = _answer(text=text)

    missing = _verdict(answer, _evidence(required_limitations=("source_incomplete",)))
    unavailable = _verdict(answer, _evidence(status=GoalEvidenceStatus.UNAVAILABLE))

    assert "required_limitation_missing:g1:source_incomplete" in missing
    assert "fact_from_unavailable_goal:c1" in unavailable


def test_limitation_claims_may_state_the_values_in_their_codes() -> None:
    text = "It depends on kv-app and sql-app. A default 86400 second window applied."
    limitation_start = text.index("A default")
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                _answer(text=text).claims[0].model_dump(mode="json")
                | {"span": {"start": 0, "end": limitation_start - 1}},
                {
                    "id": "c2",
                    "kind": "limitation",
                    "span": {"start": limitation_start, "end": len(text)},
                    "limitation_codes": ["default_window_applied:86400"],
                },
            ],
        }
    )

    assert _verdict(answer, _evidence(required_limitations=("default_window_applied:86400",))) == ()


def test_possible_impact_cannot_be_stated_as_observed() -> None:
    text = "It depends on kv-app and sql-app."

    violations = _verdict(_answer(text=text), _evidence(possible_only=True))

    assert "impact_stated_as_observed:c1" in violations
