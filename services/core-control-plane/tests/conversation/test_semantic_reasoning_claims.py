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
        utterance="What does aks-prod-01 depend on?",
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


def test_a_restatement_may_repeat_only_what_the_operator_wrote() -> None:
    text = (
        "You asked what aks-prod-01 depends on; it has 3 of them. It depends on kv-app and sql-app."
    )
    restated_end = text.index(";")
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "restatement",
                    "span": {"start": 0, "end": text.index(". It")},
                },
                _answer(text=text).claims[0].model_dump(mode="json")
                | {"id": "c2", "span": {"start": text.index("It depends"), "end": len(text)}},
            ],
        }
    )

    violations = _verdict(answer)

    assert f"undeclared_literal:{text.index('3')}" in violations
    assert f"undeclared_literal:{text.index('aks-prod-01')}" not in violations
    assert restated_end < text.index("3")


def _count_answer(text: str, value: int, **claim: Any) -> ComposedAnswer:
    start = text.index(str(value))
    body = {
        "id": "c1",
        "kind": "count",
        "span": {"start": 0, "end": len(text)},
        "refs": [{"goal": "g1", "node": "g1-count"}],
        "literals": [
            {
                "span": {"start": start, "end": start + len(str(value))},
                "value": value,
                "ref": {"goal": "g1", "node": "g1-count", "row": "aggregate:x", "field": "value"},
            }
        ],
    }
    body.update(claim)
    return ComposedAnswer.model_validate({"text": text, "claims": [body]})


def _count_evidence(count: int, status: GoalEvidenceStatus, **updates: Any) -> GoalEvidence:
    table = QueryTable(
        rows=(
            QueryRow.from_values(
                "aggregate:x", {"group": {}, "operation": "count", "value": count}
            ),
        ),
        complete=status is not GoalEvidenceStatus.UNKNOWN_INCOMPLETE,
        truncation_reason=(
            "source_incomplete" if status is GoalEvidenceStatus.UNKNOWN_INCOMPLETE else None
        ),
    )
    values: dict[str, Any] = {
        "goal_id": "g1",
        "status": status,
        "tables": {"g1-count": table},
        "authoritative_count": count,
    }
    values.update(updates)
    return GoalEvidence(**values)


def test_limitations_cannot_carry_literals_or_invented_codes() -> None:
    text = "It depends on kv-app, sql-app and vm-evil-99."
    base = _answer(text=text).claims[0].model_dump(mode="json")
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                base,
                {
                    "id": "c2",
                    "kind": "limitation",
                    "span": {"start": 0, "end": len(text)},
                    "limitation_codes": [text],
                    "literals": [
                        {
                            "span": {"start": text.index("vm-evil-99"), "end": len(text) - 1},
                            "value": "vm-evil-99",
                            "ref": {"goal": "g1", "node": "g1-side-1"},
                        }
                    ],
                },
            ],
        }
    )

    violations = _verdict(answer)

    assert "limitation_with_literals:c2" in violations
    assert "limitation_code_unknown:c2" in violations


def test_a_code_segment_exempts_only_the_exact_value_core_issued() -> None:
    text = "It depends on kv-app and sql-app. A default 400 second window applied."
    start = text.index("A default")
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                _answer(text=text).claims[0].model_dump(mode="json")
                | {"span": {"start": 0, "end": start - 1}},
                {
                    "id": "c2",
                    "kind": "limitation",
                    "span": {"start": start, "end": len(text)},
                    "limitation_codes": ["default_window_applied:86400"],
                },
            ],
        }
    )

    violations = _verdict(answer, _evidence(required_limitations=("default_window_applied:86400",)))

    assert violations == (f"undeclared_literal:{text.index('400')}",)


def test_relabelling_a_count_as_a_fact_keeps_every_count_check() -> None:
    text = "There are exactly 12 VMs."
    answer = _count_answer(text, 12, kind="fact", limitation_codes=["source_incomplete"])

    violations = _verdict(
        answer,
        _count_evidence(
            12,
            GoalEvidenceStatus.UNKNOWN_INCOMPLETE,
            required_limitations=("source_incomplete",),
        ),
    )

    assert "count_quantifier_mismatch:c1" in violations
    assert "limitation_code_outside_limitation:c1" in violations
    assert "required_limitation_missing:g1:source_incomplete" in violations


def test_possible_impact_cannot_be_stated_as_observed_under_any_kind() -> None:
    text = "kv-app and sql-app are down."
    answer = _answer(
        text=text,
        kind="state",
        literals=[_literal(text, "kv-app", "kv-1"), _literal(text, "sql-app", "sql-1")],
    )

    assert "impact_stated_as_observed:c1" in _verdict(answer, _evidence(possible_only=True))


def test_invented_identities_without_digits_are_undeclared() -> None:
    text = "It depends on kv-app, sql-app and payments-db."

    violations = _verdict(_answer(text=text))

    assert violations == (f"undeclared_literal:{text.index('payments-db')}",)


def test_a_listed_row_must_be_named_in_the_prose() -> None:
    text = "It depends only on kv-app."

    violations = _verdict(_answer(text=text, literals=[_literal(text, "kv-app", "kv-1")]))

    assert "claim_row_unshown:c1" in violations


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("의존 리소스는 12개입니다.", ()),
        ("There are \u202e12\u202c dependencies.", ("control_character",)),
    ),
)
def test_korean_counts_pass_and_format_characters_fail(
    text: str, expected: tuple[str, ...]
) -> None:
    answer = _count_answer(text, 12)

    violations = _verdict(answer, _count_evidence(12, GoalEvidenceStatus.VERIFIED))

    assert tuple(item for item in violations if not item.startswith("text_")) == expected


def test_korean_particles_never_hide_an_undeclared_name() -> None:
    text = "sql-app은 kv-app에 의존합니다."
    answer = _answer(text=text, literals=[], rows=[])

    violations = _verdict(answer, _evidence(rendered_nodes=frozenset({"g1-side-1"})))

    assert f"undeclared_literal:{text.index('sql-app')}" in violations
    assert f"undeclared_literal:{text.index('kv-app')}" in violations


def test_a_sign_before_a_count_is_rejected() -> None:
    text = "The change is -12 resources."

    violations = _verdict(_count_answer(text, 12), _count_evidence(12, GoalEvidenceStatus.VERIFIED))

    assert "literal_qualified_by_symbol:c1" in violations


def test_restatements_cannot_assert_or_overlap_facts() -> None:
    text = "It depends on kv-app and sql-app."
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "restatement",
                    "span": {"start": 0, "end": len(text)},
                    "proposition": {"polarity": "deny"},
                },
                _answer(text=text).claims[0].model_dump(mode="json") | {"id": "c2"},
            ],
        }
    )

    violations = _verdict(answer)

    assert "restatement_asserts:c1" in violations
    assert "restatement_overlaps_claim:c1" in violations


def test_a_literal_bound_to_an_uncited_goal_is_rejected_and_still_checked() -> None:
    text = "There are exactly 5 VMs."
    start = text.index("5")
    counted = _evidence(
        goal_id="g2",
        status=GoalEvidenceStatus.UNKNOWN_INCOMPLETE,
        tables={"g2-count": QueryTable(rows=(), complete=False, truncation_reason="result_limit")},
        authoritative_count=5,
    )
    answer = ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "fact",
                    "span": {"start": 0, "end": len(text)},
                    "refs": [{"goal": "g1", "node": "g1-side-1"}],
                    "rows": [],
                    "literals": [
                        {
                            "span": {"start": start, "end": start + 1},
                            "value": 5,
                            "ref": {"goal": "g2", "node": "g2-count"},
                        }
                    ],
                },
                {
                    "id": "c2",
                    "kind": "fact",
                    "span": {"start": 0, "end": len(text)},
                    "refs": [{"goal": "g2", "node": "g2-count"}],
                },
            ],
        }
    )

    violations = _verdict(answer, _evidence(), counted)

    assert "literal_goal_uncited:c1" in violations
    assert "count_quantifier_mismatch:c1" in violations


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("It depends on kv-app and sql-app\u2026", ()),
        ("It depends on kv-app\u00a0and sql-app.", ()),
        ("kv-app과 sql-app에 의존합니다 (최대 1\uff5e2홉).", ()),
        ("It depends on kv-app and sql-app (5\u00b5s).", ()),
        ("It depends on kv-app and sql-app and \uff53\uff51\uff4c.", ("text_not_normalized",)),
    ),
)
def test_only_compatibility_forms_of_ascii_letters_or_digits_are_rejected(
    text: str, expected: tuple[str, ...]
) -> None:
    violations = _verdict(_answer(text=text))

    assert tuple(item for item in violations if item == "text_not_normalized") == expected


def test_an_accepted_verdict_still_requires_the_entailment_review() -> None:
    verdict = verify_answer_claims(
        _answer(text="It depends on kv-app and sql-app."),
        evidence=(_evidence(),),
        utterance="What does aks-prod-01 depend on?",
    )

    assert verdict.accepted is True
    assert verdict.entailment_review_required is True
