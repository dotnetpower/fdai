"""Trusted repository policy for the governed SRE cohort claim.

The policy is a versioned repository artifact loaded independently of any
cohort evidence. It pins the required success metrics, every zero-threshold
guard, the actual content digest of the frozen scenario set, and the minimum
retained sample size. The only value a caller supplies is the expected pinned
revision, because that is the one fact the repository cannot know in advance.

Evidence never contributes to this policy, so a cohort artifact cannot weaken
the expectation it is measured against.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_service_contracts.baseline_cohort import (
    MINIMUM_COHORT_SAMPLE_SIZE,
    CohortClaimRequirement,
)
from fdai_service_contracts.ontology_query import content_digest

#: Repository-relative location of the trusted cohort claim policy.
COHORT_CLAIM_POLICY_PATH = "config/sre-cohort-claim-policy.json"

#: The only policy schema this loader accepts.
COHORT_CLAIM_POLICY_SCHEMA_VERSION = "1.0.0"

#: Success metrics from `docs/roadmap/architecture/goals-and-metrics.md` that a
#: published cohort claim MUST report as an absolute value with an interval.
REQUIRED_SUCCESS_METRIC_IDS: tuple[str, ...] = (
    "auto_resolution_rate",
    "change_lead_time_seconds",
    "cost_per_unit_usd",
    "human_touchpoints_per_100_events",
    "mttr_seconds",
)

#: The four guards whose threshold is exactly zero in the same document.
ZERO_THRESHOLD_GUARD_IDS: tuple[str, ...] = (
    "policy_violation_escape_rate",
    "unauthorized_execution_rate",
    "unverified_success_claim_rate",
    "wrong_target_or_stale_revision_execution_rate",
)


class CohortClaimPolicyError(ValueError):
    """Raised when the trusted cohort claim policy is absent or weakened."""


@dataclass(frozen=True, slots=True)
class CohortClaimPolicy:
    """One loaded, floor-checked cohort claim policy revision."""

    policy_id: str
    policy_version: str
    scenario_set_version: str
    scenario_set_digest: str
    minimum_sample_size: int
    required_metric_ids: tuple[str, ...]
    required_guard_ids: tuple[str, ...]
    freshness_policy_digest: str
    freshness_ceiling_seconds: int
    allowed_authority_classes: tuple[str, ...]
    allowed_source_identities: tuple[str, ...]
    purpose_id: str
    producer_id: str
    producer_version: str
    method_id: str
    method_version: str
    minimum_completeness_basis_points: int

    def verify_scenario_set(self, root: Path) -> None:
        """Fail closed unless the pinned digest is the frozen set's real content."""

        actual = frozen_scenario_set_digest(root)
        if actual != self.scenario_set_digest:
            raise CohortClaimPolicyError(
                "cohort claim policy does not pin the actual frozen scenario-set digest"
            )

    def requirement(self, *, expected_revision: str) -> CohortClaimRequirement:
        """Build the evaluated requirement from this policy and one trusted revision."""

        evidence = {
            "allowed_authority_classes": self.allowed_authority_classes,
            "allowed_source_identities": self.allowed_source_identities,
            "scope_digest": self.scenario_set_digest,
            "purpose_id": self.purpose_id,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "method_id": self.method_id,
            "method_version": self.method_version,
            "source_revision": expected_revision,
            "freshness_policy_digest": self.freshness_policy_digest,
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "minimum_completeness_basis_points": self.minimum_completeness_basis_points,
        }
        try:
            return CohortClaimRequirement.model_validate(
                {
                    "policy_id": self.policy_id,
                    "policy_version": self.policy_version,
                    "scenario_set_version": self.scenario_set_version,
                    "scenario_set_digest": self.scenario_set_digest,
                    "fdai_revision": expected_revision,
                    "minimum_sample_size": self.minimum_sample_size,
                    "required_metric_ids": self.required_metric_ids,
                    "required_guard_ids": self.required_guard_ids,
                    "baseline_evidence": evidence,
                    "treatment_evidence": evidence,
                }
            )
        except ValueError as error:
            raise CohortClaimPolicyError(
                f"cohort claim policy cannot pin the expected revision: {error}"
            ) from error


def frozen_scenario_set_digest(root: Path) -> str:
    """Return the canonical content digest of one frozen scenario-set directory."""

    try:
        paths = sorted(root.glob("*.json"))
    except OSError as error:  # pragma: no cover - unreadable directory
        raise CohortClaimPolicyError(f"unreadable frozen scenario set: {error}") from error
    if not paths:
        raise CohortClaimPolicyError(f"no frozen scenarios found under {root}")
    entries = [
        {
            "content_digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "name": path.name,
        }
        for path in paths
    ]
    return content_digest({"entries": entries, "scenario_count": len(entries)})


def load_cohort_claim_policy(path: Path) -> CohortClaimPolicy:
    """Load and floor-check the trusted cohort claim policy revision."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CohortClaimPolicyError(f"unreadable cohort claim policy: {error}") from error
    body = _mapping(raw, "policy")
    if body.get("schema_version") != COHORT_CLAIM_POLICY_SCHEMA_VERSION:
        raise CohortClaimPolicyError(
            f"cohort claim policy schema MUST be {COHORT_CLAIM_POLICY_SCHEMA_VERSION}"
        )
    minimum = body.get("minimum_sample_size")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        raise CohortClaimPolicyError("cohort claim policy minimum_sample_size MUST be an integer")
    if minimum < MINIMUM_COHORT_SAMPLE_SIZE:
        raise CohortClaimPolicyError(
            f"cohort claim policy MUST NOT weaken the {MINIMUM_COHORT_SAMPLE_SIZE}-sample floor"
        )
    metric_ids = _identifiers(body.get("required_metric_ids"), "required_metric_ids")
    guard_ids = _identifiers(body.get("required_guard_ids"), "required_guard_ids")
    _require_floor(metric_ids, REQUIRED_SUCCESS_METRIC_IDS, "success metric")
    _require_floor(guard_ids, ZERO_THRESHOLD_GUARD_IDS, "zero-threshold guard")
    evidence = _mapping(body.get("evidence"), "evidence")
    freshness = _mapping(body.get("freshness_policy"), "freshness_policy")
    ceiling = freshness.get("ceiling_seconds")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or not 0 < ceiling <= 31_536_000:
        raise CohortClaimPolicyError("cohort claim freshness ceiling MUST be bounded seconds")
    completeness = evidence.get("minimum_completeness_basis_points", 10_000)
    if not isinstance(completeness, int) or isinstance(completeness, bool):
        raise CohortClaimPolicyError("cohort claim completeness floor MUST be basis points")
    if completeness != 10_000:
        raise CohortClaimPolicyError("cohort claim policy MUST require complete evidence")
    return CohortClaimPolicy(
        policy_id=_text(body.get("policy_id"), "policy_id"),
        policy_version=_text(body.get("policy_version"), "policy_version"),
        scenario_set_version=_text(body.get("scenario_set_version"), "scenario_set_version"),
        scenario_set_digest=_digest(body.get("scenario_set_digest"), "scenario_set_digest"),
        minimum_sample_size=minimum,
        required_metric_ids=metric_ids,
        required_guard_ids=guard_ids,
        freshness_policy_digest=content_digest(
            {
                "ceiling_seconds": ceiling,
                "policy_id": _text(freshness.get("policy_id"), "freshness policy_id"),
                "policy_version": _text(
                    freshness.get("policy_version"), "freshness policy_version"
                ),
            }
        ),
        freshness_ceiling_seconds=ceiling,
        allowed_authority_classes=_identifiers(
            evidence.get("allowed_authority_classes"),
            "allowed_authority_classes",
        ),
        allowed_source_identities=_identifiers(
            evidence.get("allowed_source_identities"),
            "allowed_source_identities",
        ),
        purpose_id=_text(evidence.get("purpose_id"), "purpose_id"),
        producer_id=_text(evidence.get("producer_id"), "producer_id"),
        producer_version=_text(evidence.get("producer_version"), "producer_version"),
        method_id=_text(evidence.get("method_id"), "method_id"),
        method_version=_text(evidence.get("method_version"), "method_version"),
        minimum_completeness_basis_points=completeness,
    )


def _mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be an object")
    return raw


def _text(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be non-empty text")
    return raw


def _digest(raw: Any, name: str) -> str:
    value = _text(raw, name)
    if not value.startswith("sha256:") or len(value) != 71:
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be a SHA-256 digest")
    return value


def _identifiers(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be a non-empty array")
    values = tuple(_text(item, name) for item in raw)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be unique and ordered")
    return values


def _require_floor(values: tuple[str, ...], floor: tuple[str, ...], label: str) -> None:
    missing = sorted(set(floor) - set(values))
    if missing:
        raise CohortClaimPolicyError(
            f"cohort claim policy MUST require every {label}: missing {', '.join(missing)}"
        )


__all__ = [
    "COHORT_CLAIM_POLICY_PATH",
    "COHORT_CLAIM_POLICY_SCHEMA_VERSION",
    "REQUIRED_SUCCESS_METRIC_IDS",
    "ZERO_THRESHOLD_GUARD_IDS",
    "CohortClaimPolicy",
    "CohortClaimPolicyError",
    "frozen_scenario_set_digest",
    "load_cohort_claim_policy",
]
