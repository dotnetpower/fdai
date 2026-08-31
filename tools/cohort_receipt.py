"""Repository-safe importer for a governed baseline and treatment cohort claim.

A cohort claim bundle is produced outside this repository by governed
deployment evidence. This module only parses it, validates it against the
shipped contracts, and hands it to the deterministic evaluator. It never
authenticates evidence, never admits it, and never grants authority: a
bundle without a current independent admission stays ineligible.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.measurement.baseline_cohort_claim import evaluate_admitted_cohort_claim
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortClaimAssessment,
    CohortClaimRequirement,
    missing_cohort_claim,
)


class CohortClaimBundleError(ValueError):
    """Raised when a cohort claim bundle cannot be read as governed evidence."""


def _require_mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise CohortClaimBundleError(f"cohort claim bundle {name} MUST be an object")
    return raw


def _admission(raw: Any) -> DecisionEvidenceAdmission:
    values = _require_mapping(raw, "admission")
    try:
        return DecisionEvidenceAdmission(
            receipt_digest=str(values["receipt_digest"]),
            verification_bundle_digest=str(values["verification_bundle_digest"]),
            evidence_digest=str(values["evidence_digest"]),
            scope_digest=str(values["scope_digest"]),
            purpose_id=str(values["purpose_id"]),
            source_revision=str(values["source_revision"]),
            verified_at=_timestamp(values["verified_at"]),
            valid_until=_timestamp(values["valid_until"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CohortClaimBundleError(f"invalid cohort claim admission: {error}") from error


def _timestamp(raw: Any) -> datetime:
    value = datetime.fromisoformat(str(raw))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cohort claim timestamps MUST include a timezone")
    return value.astimezone(UTC)


def load_cohort_claim_bundle(
    path: Path,
) -> tuple[
    BaselineTreatmentCohortReceipt,
    CohortClaimRequirement,
    tuple[DecisionEvidenceAdmission, ...],
]:
    """Parse one governed bundle into its receipt, requirement, and admissions."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CohortClaimBundleError(f"unreadable cohort claim bundle: {error}") from error
    body = _require_mapping(raw, "bundle")
    try:
        receipt = BaselineTreatmentCohortReceipt.model_validate(
            _require_mapping(body.get("receipt"), "receipt")
        )
        requirement = CohortClaimRequirement.model_validate(
            _require_mapping(body.get("requirement"), "requirement")
        )
    except ValueError as error:
        raise CohortClaimBundleError(f"invalid cohort claim bundle: {error}") from error
    admissions_raw = body.get("admissions", [])
    if not isinstance(admissions_raw, list):
        raise CohortClaimBundleError("cohort claim bundle admissions MUST be an array")
    return receipt, requirement, tuple(_admission(item) for item in admissions_raw)


def evaluate_cohort_claim_bundle(
    path: Path | None,
    *,
    evaluated_at: datetime,
    expected_scenario_set_version: str | None = None,
) -> CohortClaimAssessment:
    """Return the deterministic eligibility of a bundle, or of its absence."""

    if path is None:
        return missing_cohort_claim(evaluated_at=evaluated_at)
    receipt, requirement, admissions = load_cohort_claim_bundle(path)
    if (
        expected_scenario_set_version is not None
        and requirement.scenario_set_version != expected_scenario_set_version
    ):
        raise CohortClaimBundleError(
            "cohort claim bundle does not describe the replayed frozen scenario set"
        )
    return evaluate_admitted_cohort_claim(
        receipt,
        requirement,
        admissions=admissions,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "CohortClaimBundleError",
    "evaluate_cohort_claim_bundle",
    "load_cohort_claim_bundle",
]
