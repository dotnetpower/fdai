"""Contract tests for governed operational coverage accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai_service_contracts.operational_coverage import (
    OperationalCoverageCount,
    OperationalCoverageDisposition,
    OperationalCoverageDomain,
    OperationalCoverageReceipt,
    operational_coverage_receipt_digest,
)
from pydantic import ValidationError

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _receipt(**overrides: object) -> OperationalCoverageReceipt:
    values: dict[str, object] = {
        "domain": OperationalCoverageDomain.GOVERNANCE_EVALUATION,
        "scope_digest": DIGEST_A,
        "denominator_digest": DIGEST_B,
        "denominator_count": 100,
        "disposition_counts": (
            OperationalCoverageCount(disposition="covered", count=99),
            OperationalCoverageCount(disposition="unknown", count=1),
        ),
        "evidence_digests": (DIGEST_A, DIGEST_B),
        "evidence_cutoff": NOW,
        "evaluated_at": NOW + timedelta(minutes=1),
        "fresh_until": NOW + timedelta(hours=1),
        "target_basis_points": 9_900,
        "zero_tolerance_dispositions": (
            OperationalCoverageDisposition.CONFLICTING,
            OperationalCoverageDisposition.INVALID,
        ),
        "coverage_basis_points": 9_900,
        "accounting_complete": True,
        "target_met": True,
        "execution_authority": False,
    }
    values.update(overrides)
    return OperationalCoverageReceipt(
        receipt_digest=operational_coverage_receipt_digest(**values),
        **values,
    )


def test_exact_99_percent_receipt_is_complete_and_authority_free() -> None:
    receipt = _receipt()

    assert receipt.coverage_basis_points == 9_900
    assert receipt.accounting_complete is True
    assert receipt.target_met is True
    assert receipt.execution_authority is False
    assert OperationalCoverageReceipt.model_validate_json(receipt.model_dump_json()) == receipt


def test_coverage_does_not_confuse_policy_outcome_with_evaluability() -> None:
    receipt = _receipt(domain=OperationalCoverageDomain.GOVERNANCE_EVALUATION)

    assert {item.disposition.value for item in receipt.disposition_counts} == {
        "covered",
        "unknown",
    }
    with pytest.raises(ValueError):
        OperationalCoverageDisposition("non_compliant")


def test_incomplete_accounting_cannot_claim_the_target() -> None:
    with pytest.raises(ValidationError, match="target result"):
        _receipt(
            disposition_counts=(OperationalCoverageCount(disposition="covered", count=99),),
            accounting_complete=False,
        )


def test_accounting_completeness_field_must_match_counts() -> None:
    with pytest.raises(ValidationError, match="accounting completeness"):
        _receipt(
            disposition_counts=(OperationalCoverageCount(disposition="covered", count=99),),
            accounting_complete=True,
            target_met=False,
        )


def test_coverage_rejects_overcount_and_incorrect_basis_points() -> None:
    with pytest.raises(ValidationError, match="exceed the denominator"):
        _receipt(
            disposition_counts=(
                OperationalCoverageCount(disposition="covered", count=100),
                OperationalCoverageCount(disposition="unknown", count=1),
            ),
            coverage_basis_points=10_000,
        )
    with pytest.raises(ValidationError, match="basis points"):
        _receipt(coverage_basis_points=9_901)


def test_zero_tolerance_disposition_blocks_claim_eligibility() -> None:
    receipt = _receipt(
        disposition_counts=(
            OperationalCoverageCount(disposition="conflicting", count=1),
            OperationalCoverageCount(disposition="covered", count=99),
        ),
        target_met=False,
    )

    assert receipt.accounting_complete is True
    assert receipt.coverage_basis_points == 9_900
    assert receipt.target_met is False


def test_stale_evidence_blocks_claim_eligibility() -> None:
    receipt = _receipt(
        evaluated_at=NOW + timedelta(hours=2),
        fresh_until=NOW + timedelta(hours=1),
        target_met=False,
    )

    assert receipt.target_met is False


def test_freshness_cannot_end_before_the_evidence_cutoff() -> None:
    with pytest.raises(ValidationError, match="freshness"):
        _receipt(fresh_until=NOW - timedelta(minutes=1), target_met=False)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "disposition_counts",
            (
                OperationalCoverageCount(disposition="unknown", count=1),
                OperationalCoverageCount(disposition="covered", count=99),
            ),
            "dispositions",
        ),
        ("evidence_digests", (DIGEST_B, DIGEST_A), "evidence digests"),
        (
            "zero_tolerance_dispositions",
            (
                OperationalCoverageDisposition.INVALID,
                OperationalCoverageDisposition.CONFLICTING,
            ),
            "zero-tolerance",
        ),
    ),
)
def test_replay_fields_must_be_unique_and_ordered(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _receipt(**{field: value})


def test_receipt_rejects_digest_drift_naive_time_and_extra_fields() -> None:
    receipt = _receipt()
    with pytest.raises(ValidationError, match="digest"):
        OperationalCoverageReceipt.model_validate(
            {**receipt.model_dump(), "receipt_digest": DIGEST_A}
        )
    with pytest.raises(ValidationError, match="timezone"):
        _receipt(evaluated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="Extra inputs"):
        OperationalCoverageReceipt.model_validate(
            {**receipt.model_dump(), "compliance_status": "compliant"}
        )


def test_digest_helper_canonicalizes_json_values_and_ignores_stored_digest() -> None:
    receipt = _receipt()
    body = receipt.model_dump(mode="json")

    assert operational_coverage_receipt_digest(**body) == receipt.receipt_digest
    assert OperationalCoverageReceipt.model_validate(body) == receipt


def test_equivalent_timezone_instants_share_one_canonical_digest() -> None:
    receipt = _receipt()
    kst = timezone(timedelta(hours=9))
    shifted = _receipt(
        evidence_cutoff=receipt.evidence_cutoff.astimezone(kst),
        evaluated_at=receipt.evaluated_at.astimezone(kst),
        fresh_until=receipt.fresh_until.astimezone(kst),
    )

    assert shifted.receipt_digest == receipt.receipt_digest
    assert shifted.evidence_cutoff.tzinfo is UTC
