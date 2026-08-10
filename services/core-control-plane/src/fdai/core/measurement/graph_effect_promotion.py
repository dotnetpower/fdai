"""Immutable evidence receipts for GraphEffectModel promotion."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade
from fdai.core.assurance_twin.graph_effect import GraphEffectModel

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_REVISION = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_EVIDENCE_RANK = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


@dataclass(frozen=True, slots=True)
class GraphEffectModelPromotionPolicy:
    """Fail-closed quality floor for one model scope."""

    min_samples: int = 20
    min_distinct_observation_days: int = 7
    min_confidence_lower: float = 0.9
    max_mean_absolute_error: float = 0.1
    max_mean_absolute_percentage_error: float = 0.1
    min_within_tolerance_rate: float = 0.9
    max_rollback_rate: float = 0.0
    max_recurrence_rate: float = 0.0
    max_policy_escapes: int = 0
    max_invariant_violations: int = 0
    max_simulation_review_rate: float = 0.0
    min_evidence_grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL

    def __post_init__(self) -> None:
        if self.min_samples < 1 or self.min_distinct_observation_days < 1:
            raise ValueError("graph model promotion sample and day minimums MUST be positive")
        if self.max_policy_escapes < 0 or self.max_invariant_violations < 0:
            raise ValueError("graph model promotion violation ceilings MUST be non-negative")
        rates = (
            self.min_confidence_lower,
            self.max_mean_absolute_error,
            self.max_mean_absolute_percentage_error,
            self.min_within_tolerance_rate,
            self.max_rollback_rate,
            self.max_recurrence_rate,
            self.max_simulation_review_rate,
        )
        if any(not math.isfinite(item) or not 0.0 <= item <= 1.0 for item in rates):
            raise ValueError("graph model promotion rates MUST be finite values in [0, 1]")


@dataclass(frozen=True, slots=True)
class GraphEffectModelPromotionReceipt:
    """Exact evidence and expected-pointer receipt for one model promotion."""

    fdai_revision: str
    scenario_set_version: str
    model_ref: str
    model_artifact_digest: str
    expected_active_ref: str | None
    challenger_ref: str
    rollback_ref: str | None
    ontology_release_digest: str
    property_semantics_digest: str
    causal_evidence_receipt_digest: str
    frozen_scenario_set_digest: str
    live_shadow_cohort_digest: str
    sample_count: int
    distinct_observation_days: int
    confidence_lower: float
    confidence_upper: float
    mean_absolute_error: float
    mean_absolute_percentage_error: float
    within_tolerance_rate: float
    rollback_rate: float
    recurrence_rate: float
    recurrence_window_complete: bool
    policy_escapes: int
    invariant_violations: int
    simulation_review_rate: float
    evidence_cutoff: datetime
    applicability_conditions: tuple[str, ...]
    evidence_grade: CausalEvidenceGrade
    ready: bool
    gaps: tuple[str, ...]
    receipt_digest: str
    schema_version: str = "1.0.0"

    @classmethod
    def create(
        cls,
        *,
        model: GraphEffectModel,
        fdai_revision: str,
        scenario_set_version: str,
        expected_active_ref: str | None,
        rollback_ref: str | None,
        frozen_scenario_set_digest: str,
        live_shadow_cohort_digest: str,
        distinct_observation_days: int,
        confidence_lower: float,
        confidence_upper: float,
        mean_absolute_percentage_error: float,
        within_tolerance_rate: float,
        rollback_rate: float,
        recurrence_rate: float,
        recurrence_window_complete: bool,
        policy_escapes: int,
        invariant_violations: int,
        simulation_review_rate: float,
        evidence_cutoff: datetime,
        policy: GraphEffectModelPromotionPolicy | None = None,
    ) -> GraphEffectModelPromotionReceipt:
        """Evaluate immutable evidence and issue one replay-stable receipt."""

        selected = policy or GraphEffectModelPromotionPolicy()
        if not model.promotable:
            raise ValueError("graph model lacks governed artifact identity")
        artifact_digest = model.artifact_digest
        ontology_release_digest = model.ontology_release_digest
        property_semantics_digest = model.property_semantics_digest
        if (
            artifact_digest is None
            or ontology_release_digest is None
            or property_semantics_digest is None
        ):
            raise ValueError("graph model lacks governed artifact identity")
        material: dict[str, Any] = {
            "fdai_revision": fdai_revision,
            "scenario_set_version": scenario_set_version,
            "model_ref": model.ref,
            "model_artifact_digest": artifact_digest,
            "expected_active_ref": expected_active_ref,
            "challenger_ref": model.ref,
            "rollback_ref": rollback_ref,
            "ontology_release_digest": ontology_release_digest,
            "property_semantics_digest": property_semantics_digest,
            "causal_evidence_receipt_digest": model.causal_evidence_receipt_digest,
            "frozen_scenario_set_digest": frozen_scenario_set_digest,
            "live_shadow_cohort_digest": live_shadow_cohort_digest,
            "sample_count": model.sample_count,
            "distinct_observation_days": distinct_observation_days,
            "confidence_lower": confidence_lower,
            "confidence_upper": confidence_upper,
            "mean_absolute_error": model.mean_absolute_error,
            "mean_absolute_percentage_error": mean_absolute_percentage_error,
            "within_tolerance_rate": within_tolerance_rate,
            "rollback_rate": rollback_rate,
            "recurrence_rate": recurrence_rate,
            "recurrence_window_complete": recurrence_window_complete,
            "policy_escapes": policy_escapes,
            "invariant_violations": invariant_violations,
            "simulation_review_rate": simulation_review_rate,
            "evidence_cutoff": _timestamp(evidence_cutoff),
            "applicability_conditions": list(model.applicability_conditions),
            "evidence_grade": model.evidence_grade.value,
            "schema_version": "1.0.0",
        }
        _validate_material(material)
        gaps = _promotion_gaps(material, selected)
        material["ready"] = not gaps
        material["gaps"] = list(gaps)
        material["receipt_digest"] = _content_digest(material)
        return cls.from_json(material)

    @classmethod
    def from_json(cls, value: object) -> GraphEffectModelPromotionReceipt:
        """Decode a strict retained receipt and recompute its digest."""

        if not isinstance(value, dict):
            raise ValueError("graph model promotion receipt MUST be an object")
        expected = {
            "fdai_revision",
            "scenario_set_version",
            "model_ref",
            "model_artifact_digest",
            "expected_active_ref",
            "challenger_ref",
            "rollback_ref",
            "ontology_release_digest",
            "property_semantics_digest",
            "causal_evidence_receipt_digest",
            "frozen_scenario_set_digest",
            "live_shadow_cohort_digest",
            "sample_count",
            "distinct_observation_days",
            "confidence_lower",
            "confidence_upper",
            "mean_absolute_error",
            "mean_absolute_percentage_error",
            "within_tolerance_rate",
            "rollback_rate",
            "recurrence_rate",
            "recurrence_window_complete",
            "policy_escapes",
            "invariant_violations",
            "simulation_review_rate",
            "evidence_cutoff",
            "applicability_conditions",
            "evidence_grade",
            "ready",
            "gaps",
            "receipt_digest",
            "schema_version",
        }
        if set(value) != expected:
            raise ValueError("graph model promotion receipt has unexpected fields")
        _validate_material(value)
        receipt_digest = _required_text(value, "receipt_digest")
        if receipt_digest != _content_digest(value):
            raise ValueError("graph model promotion receipt digest does not match content")
        conditions = value["applicability_conditions"]
        gaps = value["gaps"]
        if not isinstance(conditions, list) or not isinstance(gaps, list):
            raise ValueError("graph model promotion receipt arrays are invalid")
        return cls(
            fdai_revision=_required_text(value, "fdai_revision"),
            scenario_set_version=_required_text(value, "scenario_set_version"),
            model_ref=_required_text(value, "model_ref"),
            model_artifact_digest=_required_text(value, "model_artifact_digest"),
            expected_active_ref=_optional_text(value, "expected_active_ref"),
            challenger_ref=_required_text(value, "challenger_ref"),
            rollback_ref=_optional_text(value, "rollback_ref"),
            ontology_release_digest=_required_text(value, "ontology_release_digest"),
            property_semantics_digest=_required_text(value, "property_semantics_digest"),
            causal_evidence_receipt_digest=_required_text(value, "causal_evidence_receipt_digest"),
            frozen_scenario_set_digest=_required_text(value, "frozen_scenario_set_digest"),
            live_shadow_cohort_digest=_required_text(value, "live_shadow_cohort_digest"),
            sample_count=_integer(value, "sample_count"),
            distinct_observation_days=_integer(value, "distinct_observation_days"),
            confidence_lower=_number(value, "confidence_lower"),
            confidence_upper=_number(value, "confidence_upper"),
            mean_absolute_error=_number(value, "mean_absolute_error"),
            mean_absolute_percentage_error=_number(value, "mean_absolute_percentage_error"),
            within_tolerance_rate=_number(value, "within_tolerance_rate"),
            rollback_rate=_number(value, "rollback_rate"),
            recurrence_rate=_number(value, "recurrence_rate"),
            recurrence_window_complete=bool(value["recurrence_window_complete"]),
            policy_escapes=_integer(value, "policy_escapes"),
            invariant_violations=_integer(value, "invariant_violations"),
            simulation_review_rate=_number(value, "simulation_review_rate"),
            evidence_cutoff=_parse_timestamp(_required_text(value, "evidence_cutoff")),
            applicability_conditions=tuple(conditions),
            evidence_grade=CausalEvidenceGrade(_required_text(value, "evidence_grade")),
            ready=bool(value["ready"]),
            gaps=tuple(gaps),
            receipt_digest=receipt_digest,
            schema_version=_required_text(value, "schema_version"),
        )

    def as_json(self) -> dict[str, object]:
        """Return canonical JSON-compatible receipt content."""

        return {
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "model_ref": self.model_ref,
            "model_artifact_digest": self.model_artifact_digest,
            "expected_active_ref": self.expected_active_ref,
            "challenger_ref": self.challenger_ref,
            "rollback_ref": self.rollback_ref,
            "ontology_release_digest": self.ontology_release_digest,
            "property_semantics_digest": self.property_semantics_digest,
            "causal_evidence_receipt_digest": self.causal_evidence_receipt_digest,
            "frozen_scenario_set_digest": self.frozen_scenario_set_digest,
            "live_shadow_cohort_digest": self.live_shadow_cohort_digest,
            "sample_count": self.sample_count,
            "distinct_observation_days": self.distinct_observation_days,
            "confidence_lower": self.confidence_lower,
            "confidence_upper": self.confidence_upper,
            "mean_absolute_error": self.mean_absolute_error,
            "mean_absolute_percentage_error": self.mean_absolute_percentage_error,
            "within_tolerance_rate": self.within_tolerance_rate,
            "rollback_rate": self.rollback_rate,
            "recurrence_rate": self.recurrence_rate,
            "recurrence_window_complete": self.recurrence_window_complete,
            "policy_escapes": self.policy_escapes,
            "invariant_violations": self.invariant_violations,
            "simulation_review_rate": self.simulation_review_rate,
            "evidence_cutoff": _timestamp(self.evidence_cutoff),
            "applicability_conditions": list(self.applicability_conditions),
            "evidence_grade": self.evidence_grade.value,
            "ready": self.ready,
            "gaps": list(self.gaps),
            "receipt_digest": self.receipt_digest,
            "schema_version": self.schema_version,
        }


def _promotion_gaps(
    value: dict[str, Any],
    policy: GraphEffectModelPromotionPolicy,
) -> tuple[str, ...]:
    gaps: list[str] = []
    checks = (
        (value["sample_count"] < policy.min_samples, "sample_count_below_minimum"),
        (
            value["distinct_observation_days"] < policy.min_distinct_observation_days,
            "observation_days_below_minimum",
        ),
        (value["confidence_lower"] < policy.min_confidence_lower, "confidence_below_minimum"),
        (
            value["mean_absolute_error"] > policy.max_mean_absolute_error,
            "mean_absolute_error_above_maximum",
        ),
        (
            value["mean_absolute_percentage_error"] > policy.max_mean_absolute_percentage_error,
            "mean_absolute_percentage_error_above_maximum",
        ),
        (
            value["within_tolerance_rate"] < policy.min_within_tolerance_rate,
            "within_tolerance_below_minimum",
        ),
        (value["rollback_rate"] > policy.max_rollback_rate, "rollback_rate_above_maximum"),
        (value["recurrence_rate"] > policy.max_recurrence_rate, "recurrence_rate_above_maximum"),
        (not value["recurrence_window_complete"], "recurrence_window_incomplete"),
        (value["policy_escapes"] > policy.max_policy_escapes, "policy_escape_detected"),
        (
            value["invariant_violations"] > policy.max_invariant_violations,
            "invariant_violation_detected",
        ),
        (
            value["simulation_review_rate"] > policy.max_simulation_review_rate,
            "simulation_review_rate_above_maximum",
        ),
        (
            _EVIDENCE_RANK[CausalEvidenceGrade(value["evidence_grade"])]
            < _EVIDENCE_RANK[policy.min_evidence_grade],
            "causal_evidence_grade_below_minimum",
        ),
    )
    gaps.extend(reason for failed, reason in checks if failed)
    return tuple(gaps)


def _validate_material(value: dict[str, Any]) -> None:
    if _REVISION.fullmatch(_required_text(value, "fdai_revision")) is None:
        raise ValueError("graph model promotion FDAI revision MUST be immutable")
    if _IDENTIFIER.fullmatch(_required_text(value, "scenario_set_version")) is None:
        raise ValueError("graph model promotion scenario version MUST be canonical")
    for key in (
        "model_artifact_digest",
        "ontology_release_digest",
        "property_semantics_digest",
        "causal_evidence_receipt_digest",
        "frozen_scenario_set_digest",
        "live_shadow_cohort_digest",
    ):
        if _DIGEST.fullmatch(_required_text(value, key)) is None:
            raise ValueError(f"graph model promotion {key} MUST be SHA-256")
    for key in (
        "sample_count",
        "distinct_observation_days",
        "policy_escapes",
        "invariant_violations",
    ):
        if _integer(value, key) < 0:
            raise ValueError(f"graph model promotion {key} MUST be non-negative")
    rates = tuple(
        _number(value, key)
        for key in (
            "confidence_lower",
            "confidence_upper",
            "mean_absolute_error",
            "mean_absolute_percentage_error",
            "within_tolerance_rate",
            "rollback_rate",
            "recurrence_rate",
            "simulation_review_rate",
        )
    )
    if any(not 0.0 <= item <= 1.0 for item in rates) or rates[0] > rates[1]:
        raise ValueError("graph model promotion confidence and rates MUST be in [0, 1]")
    if not isinstance(value.get("recurrence_window_complete"), bool):
        raise ValueError("graph model promotion recurrence completeness MUST be boolean")
    conditions = value.get("applicability_conditions")
    if (
        not isinstance(conditions, list)
        or not conditions
        or any(not isinstance(item, str) or not item for item in conditions)
        or conditions != sorted(set(conditions))
    ):
        raise ValueError("graph model promotion applicability conditions MUST be canonical")
    for key in ("expected_active_ref", "rollback_ref"):
        _optional_text(value, key)
    if value.get("expected_active_ref") != value.get("rollback_ref"):
        raise ValueError("graph model promotion rollback ref MUST equal expected active ref")
    if _required_text(value, "model_ref") != _required_text(value, "challenger_ref"):
        raise ValueError("graph model promotion challenger ref MUST equal model ref")
    _parse_timestamp(_required_text(value, "evidence_cutoff"))
    CausalEvidenceGrade(_required_text(value, "evidence_grade"))
    if value.get("ready") is not None:
        if not isinstance(value.get("ready"), bool):
            raise ValueError("graph model promotion ready MUST be boolean")
        gaps = value.get("gaps")
        if not isinstance(gaps, list) or any(not isinstance(item, str) for item in gaps):
            raise ValueError("graph model promotion gaps MUST be a string array")
        if bool(gaps) == bool(value["ready"]):
            raise ValueError("graph model promotion ready and gaps are inconsistent")


def _content_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        {key: item for key, item in value.items() if key != "receipt_digest"},
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"graph model promotion {key} MUST be non-empty")
    return item


def _optional_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item:
        raise ValueError(f"graph model promotion {key} MUST be non-empty when present")
    return item


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"graph model promotion {key} MUST be an integer")
    return item


def _number(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
        raise ValueError(f"graph model promotion {key} MUST be finite")
    return float(item)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("graph model promotion evidence cutoff MUST be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("graph model promotion evidence cutoff MUST be timezone-aware")
    return parsed.astimezone(UTC)


__all__ = [
    "GraphEffectModelPromotionPolicy",
    "GraphEffectModelPromotionReceipt",
]
