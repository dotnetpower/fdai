from datetime import UTC, datetime

import pytest
from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCompletion,
    BaselineEvaluationCoverage,
    BaselineEvaluationCoverageLimitation,
    BaselineEvaluationOutcome,
    BaselineEvaluationTerminalOutcome,
    baseline_evaluation_completion_digest,
    baseline_evaluation_coverage_digest,
    baseline_evaluation_outcome_digest,
)
from fdai_service_contracts.schema import PackageResourceSchemaRegistry
from pydantic import ValidationError

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
DIGEST_F = "sha256:" + "f" * 64


def _outcome_values(
    *,
    outcome: BaselineEvaluationTerminalOutcome = BaselineEvaluationTerminalOutcome.COMPLIANT,
    reason_code: str | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "generation_id": "generation:one",
        "generation_digest": DIGEST_A,
        "inventory_observation_digest": DIGEST_B,
        "resource_ref": "resource:one",
        "resource_digest": DIGEST_C,
        "catalog_revision": DIGEST_D,
        "rule_ref": "rule:one",
        "rule_revision": DIGEST_E,
        "expected_denominator": 3,
        "outcome": outcome,
        "reason_code": reason_code,
        "evaluation_receipt_ref": "evaluation:one",
        "evaluation_receipt_digest": DIGEST_F,
        "saga_audit_ref": "audit:one",
        "saga_audit_digest": DIGEST_A,
        "evaluated_at": datetime(2026, 10, 2, tzinfo=UTC),
        "execution_authority": False,
    }
    values["outcome_digest"] = baseline_evaluation_outcome_digest(**values)
    return values


def _completion_values() -> dict[str, object]:
    values: dict[str, object] = {
        "generation_id": "generation:one",
        "generation_digest": DIGEST_A,
        "inventory_observation_digest": DIGEST_B,
        "catalog_revision": DIGEST_D,
        "expected_denominator": 3,
        "compliant_count": 1,
        "violated_count": 1,
        "abstained_count": 1,
        "outcome_set_digest": DIGEST_C,
        "completion_receipt_ref": "completion:one",
        "completion_receipt_digest": DIGEST_E,
        "saga_audit_ref": "audit:completion",
        "saga_audit_digest": DIGEST_F,
        "completed_at": datetime(2026, 10, 2, tzinfo=UTC),
        "complete": True,
        "projection_authority": False,
        "execution_authority": False,
    }
    values["completion_digest"] = baseline_evaluation_completion_digest(**values)
    return values


def test_outcome_binds_terminal_result_to_generation_catalog_rule_and_audit() -> None:
    outcome = BaselineEvaluationOutcome.model_validate(_outcome_values())

    assert outcome.schema_version == "1.0.0"
    assert outcome.outcome is BaselineEvaluationTerminalOutcome.COMPLIANT
    assert outcome.expected_denominator == 3
    assert outcome.execution_authority is False


def test_abstained_outcome_requires_reason_without_weakening_other_outcomes() -> None:
    with pytest.raises(ValidationError, match="abstained"):
        BaselineEvaluationOutcome.model_validate(
            _outcome_values(outcome=BaselineEvaluationTerminalOutcome.ABSTAINED)
        )

    valid = BaselineEvaluationOutcome.model_validate(
        _outcome_values(
            outcome=BaselineEvaluationTerminalOutcome.ABSTAINED,
            reason_code="missing_evidence",
        )
    )
    assert valid.reason_code == "missing_evidence"

    with pytest.raises(ValidationError, match="non-abstained"):
        BaselineEvaluationOutcome.model_validate(_outcome_values(reason_code="not-needed"))


def test_outcome_rejects_digest_mismatch_and_naive_time() -> None:
    values = _outcome_values()
    values["outcome_digest"] = DIGEST_A
    with pytest.raises(ValidationError, match="digest mismatch"):
        BaselineEvaluationOutcome.model_validate(values)

    values = _outcome_values()
    values["evaluated_at"] = datetime(2026, 10, 2)
    values["outcome_digest"] = baseline_evaluation_outcome_digest(**values)
    with pytest.raises(ValidationError, match="timezone-aware"):
        BaselineEvaluationOutcome.model_validate(values)


def test_completion_closes_exact_denominator_and_allows_empty_inventory() -> None:
    completion = BaselineEvaluationCompletion.model_validate(_completion_values())
    assert completion.expected_denominator == 3
    assert completion.compliant_count + completion.violated_count + completion.abstained_count == 3
    assert completion.projection_authority is False

    empty = _completion_values()
    empty.update(
        {
            "expected_denominator": 0,
            "compliant_count": 0,
            "violated_count": 0,
            "abstained_count": 0,
        }
    )
    empty["completion_digest"] = baseline_evaluation_completion_digest(**empty)
    assert BaselineEvaluationCompletion.model_validate(empty).expected_denominator == 0


def test_completion_rejects_incomplete_or_fabricated_denominator() -> None:
    values = _completion_values()
    values["abstained_count"] = 0
    values["completion_digest"] = baseline_evaluation_completion_digest(**values)
    with pytest.raises(ValidationError, match="counts MUST match"):
        BaselineEvaluationCompletion.model_validate(values)

    values = _completion_values()
    values["completion_digest"] = DIGEST_A
    with pytest.raises(ValidationError, match="digest mismatch"):
        BaselineEvaluationCompletion.model_validate(values)


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("baseline-evaluation-outcome", BaselineEvaluationOutcome),
        ("baseline-evaluation-completion", BaselineEvaluationCompletion),
        ("baseline-evaluation-coverage", BaselineEvaluationCoverage),
    ],
)
def test_registry_latest_schema_matches_active_baseline_evaluation_model(
    name: str,
    model: (
        type[BaselineEvaluationOutcome]
        | type[BaselineEvaluationCompletion]
        | type[BaselineEvaluationCoverage]
    ),
) -> None:
    expected = dict(model.model_json_schema())
    expected["$id"] = f"https://fdai.dev/service-contracts/{name}/1.0.0"

    assert PackageResourceSchemaRegistry().get(name) == expected


def _coverage_values(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "generation_id": "generation:one",
        "generation_digest": DIGEST_A,
        "inventory_observation_digest": DIGEST_B,
        "rule_activation_generation_id": "rule-activation-" + "a" * 32,
        "rule_activation_generation_digest": DIGEST_C,
        "rule_catalog_digest": DIGEST_D,
        "evaluated_rule_catalog_digest": DIGEST_D,
        "dispatch_signal": "inventory.resource_observed",
        "expected_pair_set_digest": DIGEST_E,
        "expected_pair_count": 3,
        "covered_pair_count": 3,
        "compliant_count": 1,
        "violated_count": 1,
        "abstained_count": 1,
        "missing_pair_count": 0,
        "duplicate_pair_count": 0,
        "conflicting_pair_count": 0,
        "unexpected_pair_count": 0,
        "revision_mismatch_count": 0,
        "outcome_set_digest": DIGEST_F,
        "complete": True,
        "limitations": (),
        "audit_ref": "audit:coverage",
        "audit_digest": DIGEST_A,
        "completed_at": datetime(2026, 10, 7, tzinfo=UTC),
        "projection_authority": False,
        "execution_authority": False,
        **changes,
    }
    values["coverage_digest"] = baseline_evaluation_coverage_digest(**values)
    return values


def test_coverage_binds_activation_and_independent_denominator() -> None:
    coverage = BaselineEvaluationCoverage.model_validate(_coverage_values())
    assert coverage.complete is True
    assert coverage.rule_activation_generation_id.startswith("rule-activation-")

    incomplete = BaselineEvaluationCoverage.model_validate(
        _coverage_values(
            covered_pair_count=2,
            abstained_count=0,
            missing_pair_count=1,
            complete=False,
            limitations=(BaselineEvaluationCoverageLimitation.PAIR_MISSING,),
        )
    )
    assert incomplete.limitations == (BaselineEvaluationCoverageLimitation.PAIR_MISSING,)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"covered_pair_count": 2}, "outcome counts"),
        (
            {"expected_pair_count": 1, "covered_pair_count": 2, "abstained_count": 0},
            "cannot exceed",
        ),
        ({"missing_pair_count": 1}, "limitations MUST match"),
        (
            {
                "missing_pair_count": 1,
                "limitations": (BaselineEvaluationCoverageLimitation.PAIR_MISSING,),
            },
            "complete MUST follow",
        ),
        ({"complete": False}, "complete MUST follow"),
        ({"completed_at": datetime(2026, 10, 7)}, "timezone-aware"),
    ],
)
def test_coverage_rejects_inconsistent_denominators(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        BaselineEvaluationCoverage.model_validate(_coverage_values(**changes))


def test_coverage_rejects_digest_mismatch_and_authority() -> None:
    values = _coverage_values()
    values["coverage_digest"] = DIGEST_B
    with pytest.raises(ValidationError, match="digest mismatch"):
        BaselineEvaluationCoverage.model_validate(values)
    with pytest.raises(ValidationError):
        BaselineEvaluationCoverage.model_validate(
            {**_coverage_values(), "execution_authority": True}
        )
