"""Deterministic Best Practice checklist evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.readiness import ChecklistControlStatus, evaluate_best_practices
from fdai.shared.contracts.models import (
    BestPractice,
    BestPracticeRequirement,
    Category,
    Provenance,
    RequirementKind,
    RequirementMode,
    RequirementOutcome,
    RequirementStatus,
    Severity,
)

_NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _control(*requirements: BestPracticeRequirement, mode: RequirementMode = RequirementMode.ALL):
    return BestPractice(
        id="azure-waf.reliability.re-09",
        version="1.0.0",
        framework="azure-waf",
        control_id="RE:09",
        title="Test disaster recovery",
        rationale="Recovery evidence must be current.",
        severity=Severity.HIGH,
        category=Category.RELIABILITY,
        requirement_mode=mode,
        requirements=tuple(requirements),
        provenance=Provenance.model_validate(
            {
                "source_url": "https://example.com/control",
                "resolved_ref": "revision",
                "content_hash": "sha256:example",
                "license": "CC-BY-4.0",
                "redistribution": "embeddable",
                "retrieved_at": _NOW,
            }
        ),
    )


def _requirement(ref: str, *, freshness_days: int | None = None) -> BestPracticeRequirement:
    return BestPracticeRequirement(
        kind=RequirementKind.ARTIFACT,
        ref=ref,
        freshness_days=freshness_days,
    )


def _outcome(
    ref: str,
    status: RequirementStatus,
    *,
    observed_at: datetime | None = None,
) -> RequirementOutcome:
    return RequirementOutcome(
        kind=RequirementKind.ARTIFACT,
        ref=ref,
        status=status,
        evidence_refs=(f"evidence://{ref}",),
        observed_at=observed_at,
    )


def test_missing_outcome_is_unknown_not_pass() -> None:
    control = _control(_requirement("dr-plan"))

    (result,) = evaluate_best_practices((control,), (), evaluated_at=_NOW)

    assert result.status is ChecklistControlStatus.UNKNOWN
    assert result.requirement_refs == ("dr-plan",)


def test_freshness_boundary_is_stale() -> None:
    control = _control(_requirement("drill", freshness_days=30))
    outcome = _outcome(
        "drill",
        RequirementStatus.SATISFIED,
        observed_at=_NOW - timedelta(days=30),
    )

    (result,) = evaluate_best_practices((control,), (outcome,), evaluated_at=_NOW)

    assert result.status is ChecklistControlStatus.STALE


def test_not_applicable_requirements_are_neutral() -> None:
    control = _control(_requirement("not-used"))
    outcome = _outcome("not-used", RequirementStatus.NOT_APPLICABLE)

    (result,) = evaluate_best_practices((control,), (outcome,), evaluated_at=_NOW)

    assert result.status is ChecklistControlStatus.NOT_APPLICABLE


def test_any_mode_passes_when_one_applicable_requirement_passes() -> None:
    control = _control(
        _requirement("primary"),
        _requirement("alternate"),
        mode=RequirementMode.ANY,
    )
    outcomes = (
        _outcome("primary", RequirementStatus.FAILED),
        _outcome("alternate", RequirementStatus.SATISFIED),
    )

    (result,) = evaluate_best_practices((control,), outcomes, evaluated_at=_NOW)

    assert result.status is ChecklistControlStatus.SATISFIED


def test_duplicate_outcomes_fail_closed() -> None:
    control = _control(_requirement("dr-plan"))
    outcome = _outcome("dr-plan", RequirementStatus.SATISFIED)

    with pytest.raises(ValueError, match="duplicate requirement outcome"):
        evaluate_best_practices((control,), (outcome, outcome), evaluated_at=_NOW)
