from __future__ import annotations

from scripts.automation.conversation_assurance_answer_gate import (
    RUBRIC_NAMES,
    ObjectiveOracleGate,
    TenPointEvaluation,
    evaluate_objective_oracle,
    rubric_result,
)


def _evaluation(
    *,
    failed: str | None = None,
    not_applicable: frozenset[str] = frozenset(),
    oracle: ObjectiveOracleGate | None = None,
) -> TenPointEvaluation:
    return TenPointEvaluation(
        rubrics=tuple(
            rubric_result(
                name,
                None if name in not_applicable else name != failed,
                "measured",
            )
            for name in RUBRIC_NAMES
        ),
        objective_oracle_gate=oracle
        or ObjectiveOracleGate(
            applicable=False,
            passed=True,
            reason="challenge has no objective oracle",
        ),
    )


def _count_payload(
    value: str,
    *,
    authority: str = "server_ontology_manifest",
    status: str = "verified",
) -> dict[str, object]:
    return {
        "source": authority,
        "verification": {"status": status, "authority": authority},
        "presentation_artifact": {
            "schema_version": 3,
            "blocks": [
                {
                    "kind": "summary",
                    "data": {
                        "items": [
                            {"label": "operation", "value": "count"},
                            {"label": "value", "value": value},
                        ]
                    },
                }
            ],
        },
    }


def test_wrong_structured_count_fails_even_when_all_ten_rubrics_pass() -> None:
    oracle = evaluate_objective_oracle(
        "ontology_action_count",
        _count_payload("44"),
        expected_authority="server_ontology_manifest",
        expected_value_provider=lambda: 49,
    )
    evaluation = _evaluation(oracle=oracle)

    assert evaluation.total_score == 10
    assert evaluation.max_score == 10
    assert evaluation.mandatory_gate_failures == ("objective_oracle",)
    assert oracle.actual_value == 44
    assert oracle.expected_value == 49
    assert not evaluation.assurance_passed


def test_wrong_authority_fails_even_at_nine_of_ten() -> None:
    evaluation = _evaluation(failed="authority_safety")

    assert evaluation.total_score == 9
    assert evaluation.mandatory_gate_failures == ("authority_safety",)
    assert not evaluation.assurance_passed


def test_missing_grounding_fails_a_fluent_nine_of_ten_answer() -> None:
    evaluation = _evaluation(failed="grounding")

    assert evaluation.total_score == 9
    assert evaluation.mandatory_gate_failures == ("grounding",)
    assert not evaluation.assurance_passed


def test_honest_unverified_answer_is_not_question_success() -> None:
    evaluation = _evaluation(failed="verification")

    assert evaluation.rubrics[0].score == 1
    assert evaluation.rubrics[1].score == 1
    assert not evaluation.technical_verified
    assert not evaluation.assurance_passed


def test_non_applicable_rubrics_are_neutral_and_keep_ten_entries() -> None:
    evaluation = _evaluation(
        not_applicable=frozenset({"visualization", "investigation_detail", "execution_detail"})
    )

    assert len(evaluation.rubrics) == 10
    assert evaluation.total_score == 7
    assert evaluation.max_score == 7
    assert evaluation.assurance_passed
    assert all(
        item.score is None
        for item in evaluation.rubrics
        if item.name in {"visualization", "investigation_detail", "execution_detail"}
    )


def test_status_fields_separate_product_verification_from_assurance() -> None:
    evaluation = _evaluation(failed="grounding")

    record = evaluation.to_dict()

    assert record["technical_verified"] is True
    assert record["assurance_passed"] is False
    assert record["mandatory_gate"] == {
        "passed": False,
        "failures": ["grounding"],
        "objective_oracle": {
            "name": "objective_oracle",
            "applicable": False,
            "passed": True,
            "reason": "challenge has no objective oracle",
            "expected_value": None,
            "actual_value": None,
        },
    }
