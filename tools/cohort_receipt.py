"""Repository-safe importer for a governed baseline and treatment cohort claim.

A cohort claim artifact is produced outside this repository by governed
deployment evidence. This module only parses the retained receipt, validates it
against the shipped contracts, and hands it to the deterministic evaluator.

Two things it deliberately never reads from the artifact:

- the :class:`CohortClaimRequirement`, which comes from the trusted versioned
  repository policy, so an artifact cannot weaken what it is measured against,
  and
- any :class:`DecisionEvidenceAdmission`, which comes only from an injected
  trusted admission provider. An importer without a provider therefore always
  leaves the claim ineligible, no matter what digests the artifact invents.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from fdai.core.measurement.baseline_cohort_claim import evaluate_admitted_cohort_claim
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortClaimAssessment,
    CohortClaimRequirement,
    missing_cohort_claim,
)

#: Keys an artifact MUST NOT carry, because each one would let the artifact
#: describe its own eligibility instead of being measured by trusted inputs.
UNTRUSTED_BUNDLE_KEYS: tuple[str, ...] = (
    "admissions",
    "admitted_receipt_digests",
    "claim_eligible",
    "policy",
    "requirement",
    "verification_bundles",
)


class CohortClaimBundleError(ValueError):
    """Raised when a cohort claim artifact cannot be read as governed evidence."""


class CohortAdmissionProvider(Protocol):
    """Return the trusted admissions currently covering one cohort receipt."""

    def admissions_for(
        self,
        receipt: BaselineTreatmentCohortReceipt,
    ) -> tuple[DecisionEvidenceAdmission, ...]: ...


def _require_mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise CohortClaimBundleError(f"cohort claim bundle {name} MUST be an object")
    return raw


def load_cohort_claim_receipt(path: Path) -> BaselineTreatmentCohortReceipt:
    """Parse one governed artifact into its retained receipt and nothing else."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CohortClaimBundleError(f"unreadable cohort claim bundle: {error}") from error
    body = _require_mapping(raw, "bundle")
    present = sorted(key for key in UNTRUSTED_BUNDLE_KEYS if key in body)
    if present:
        raise CohortClaimBundleError(
            "a cohort claim bundle MUST NOT carry its own trust inputs: " + ", ".join(present)
        )
    try:
        return BaselineTreatmentCohortReceipt.model_validate(
            _require_mapping(body.get("receipt"), "receipt")
        )
    except ValueError as error:
        raise CohortClaimBundleError(f"invalid cohort claim bundle: {error}") from error


def evaluate_cohort_claim_bundle(
    path: Path | None,
    requirement: CohortClaimRequirement,
    *,
    evaluated_at: datetime,
    admission_provider: CohortAdmissionProvider | None = None,
    expected_scenario_set_version: str | None = None,
) -> CohortClaimAssessment:
    """Return the deterministic eligibility of an artifact, or of its absence."""

    if path is None:
        return missing_cohort_claim(evaluated_at=evaluated_at)
    receipt = load_cohort_claim_receipt(path)
    if (
        expected_scenario_set_version is not None
        and requirement.scenario_set_version != expected_scenario_set_version
    ):
        raise CohortClaimBundleError(
            "cohort claim policy does not describe the replayed frozen scenario set"
        )
    admissions = () if admission_provider is None else admission_provider.admissions_for(receipt)
    return evaluate_admitted_cohort_claim(
        receipt,
        requirement,
        admissions=admissions,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "UNTRUSTED_BUNDLE_KEYS",
    "CohortAdmissionProvider",
    "CohortClaimBundleError",
    "evaluate_cohort_claim_bundle",
    "load_cohort_claim_receipt",
]
