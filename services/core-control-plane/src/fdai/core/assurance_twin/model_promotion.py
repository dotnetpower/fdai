"""Governed evidence contract for activating an immutable graph effect model."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_INVARIANT_EVIDENCE = 64
_EVIDENCE_RANK = {
    CausalEvidenceGrade.ASSOCIATION: 0,
    CausalEvidenceGrade.PREDICTIVE_PRECEDENCE: 1,
    CausalEvidenceGrade.QUASI_EXPERIMENTAL: 2,
    CausalEvidenceGrade.INTERVENTIONAL: 3,
}


class GraphModelRisk(StrEnum):
    """Policy risk class for promotion evidence, independent of action authority."""

    STANDARD = "standard"
    HIGH = "high"


class GraphModelEvidenceCohort(StrEnum):
    """Frozen source population used to score one model revision."""

    FROZEN_BENCHMARK = "frozen_benchmark"
    LIVE_SHADOW = "live_shadow"


@dataclass(frozen=True, slots=True)
class GraphModelActivePointer:
    """Mutable active slot state; model artifacts referenced here remain immutable."""

    slot_digest: str
    revision: int
    active_model_ref: str | None
    active_model_digest: str | None
    prior_active_model_ref: str | None
    prior_active_model_digest: str | None
    promotion_receipt_digest: str

    def __post_init__(self) -> None:
        _require_digest(self.slot_digest, "active pointer slot")
        _require_digest(self.promotion_receipt_digest, "active pointer receipt")
        if self.revision < 1:
            raise ValueError("active pointer revision MUST be positive")
        _validate_optional_model_identity(
            self.active_model_ref,
            self.active_model_digest,
            "active pointer model",
        )
        _validate_optional_model_identity(
            self.prior_active_model_ref,
            self.prior_active_model_digest,
            "active pointer prior model",
        )


@dataclass(frozen=True, slots=True)
class GraphModelPromotionPolicy:
    """Deterministic evidence floor applied without changing execution authority."""

    min_evidence_grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL
    require_interventional_for_high_risk: bool = True
    min_samples: int = 1
    min_fidelity: float = 0.0
    max_recurrence_rate: float = 0.0
    max_policy_escapes: int = 0

    def __post_init__(self) -> None:
        if self.min_samples < 1 or self.max_policy_escapes < 0:
            raise ValueError("graph model promotion count thresholds MUST be valid")
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in (self.min_fidelity, self.max_recurrence_rate)
        ):
            raise ValueError("graph model promotion rate thresholds MUST be in [0, 1]")
        if not isinstance(self.min_evidence_grade, CausalEvidenceGrade):
            raise ValueError("graph model promotion evidence grade is invalid")


@dataclass(frozen=True, slots=True)
class GraphModelPromotionReceipt:
    """Immutable evidence binding one challenger revision to one active-pointer CAS."""

    model_id: str
    model_version: str
    model_revision: int
    model_digest: str
    slot_digest: str
    ontology_release_digest: str
    property_semantics_digest: str
    causal_receipt_digest: str
    evidence_grade: CausalEvidenceGrade
    cohort: GraphModelEvidenceCohort
    risk: GraphModelRisk
    sample_count: int
    confidence_interval_lower: float
    confidence_interval_upper: float
    fidelity: float
    recurrence_window_complete: bool
    recurrence_rate: float
    policy_escapes: int
    invariant_evidence_digests: tuple[str, ...]
    expected_pointer_revision: int
    rollback_model_ref: str | None
    rollback_model_digest: str | None
    sealed_at: datetime

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_version or self.model_revision < 1:
            raise ValueError("graph model promotion model identity MUST be complete")
        for value, name in (
            (self.model_digest, "model"),
            (self.slot_digest, "slot"),
            (self.ontology_release_digest, "ontology release"),
            (self.property_semantics_digest, "property semantics"),
            (self.causal_receipt_digest, "causal receipt"),
        ):
            _require_digest(value, f"graph model promotion {name}")
        if self.sample_count < 1 or self.policy_escapes < 0:
            raise ValueError("graph model promotion counts MUST be valid")
        numeric = (
            self.confidence_interval_lower,
            self.confidence_interval_upper,
            self.fidelity,
            self.recurrence_rate,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in numeric):
            raise ValueError("graph model promotion evidence rates MUST be in [0, 1]")
        if not (self.confidence_interval_lower <= self.fidelity <= self.confidence_interval_upper):
            raise ValueError(
                "graph model promotion fidelity MUST be inside its confidence interval"
            )
        if not isinstance(self.recurrence_window_complete, bool):
            raise ValueError("graph model promotion recurrence completeness MUST be boolean")
        if not 1 <= len(self.invariant_evidence_digests) <= _MAX_INVARIANT_EVIDENCE or len(
            set(self.invariant_evidence_digests)
        ) != len(self.invariant_evidence_digests):
            raise ValueError("graph model promotion invariant evidence MUST be unique and bounded")
        if any(_DIGEST.fullmatch(item) is None for item in self.invariant_evidence_digests):
            raise ValueError("graph model promotion invariant evidence MUST use SHA-256")
        object.__setattr__(
            self,
            "invariant_evidence_digests",
            tuple(sorted(self.invariant_evidence_digests)),
        )
        if self.expected_pointer_revision < 0:
            raise ValueError("graph model promotion expected pointer revision MUST be non-negative")
        _validate_optional_model_identity(
            self.rollback_model_ref,
            self.rollback_model_digest,
            "graph model promotion rollback target",
        )
        if self.sealed_at.tzinfo is None:
            raise ValueError("graph model promotion sealed_at MUST be timezone-aware")

    @property
    def model_ref(self) -> str:
        """Return the exact immutable model revision named by this receipt."""

        return f"{self.model_id}@{self.model_version}:r{self.model_revision}"

    @property
    def content_digest(self) -> str:
        """Return the canonical digest used as the immutable receipt key."""

        return _content_digest(
            {
                "causal_receipt_digest": self.causal_receipt_digest,
                "cohort": self.cohort.value,
                "confidence_interval_lower": self.confidence_interval_lower,
                "confidence_interval_upper": self.confidence_interval_upper,
                "evidence_grade": self.evidence_grade.value,
                "expected_pointer_revision": self.expected_pointer_revision,
                "fidelity": self.fidelity,
                "invariant_evidence_digests": self.invariant_evidence_digests,
                "model_digest": self.model_digest,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "model_version": self.model_version,
                "ontology_release_digest": self.ontology_release_digest,
                "policy_escapes": self.policy_escapes,
                "property_semantics_digest": self.property_semantics_digest,
                "recurrence_rate": self.recurrence_rate,
                "recurrence_window_complete": self.recurrence_window_complete,
                "risk": self.risk.value,
                "rollback_model_digest": self.rollback_model_digest,
                "rollback_model_ref": self.rollback_model_ref,
                "sample_count": self.sample_count,
                "sealed_at": self.sealed_at.astimezone(UTC).isoformat(),
                "slot_digest": self.slot_digest,
            }
        )


def graph_effect_model_digest(model: GraphEffectModel) -> str:
    """Hash every behavior-bearing field of one immutable model snapshot."""

    return _content_digest(
        {
            "applied_observation_digests": model.applied_observation_digests,
            "causal_evidence_receipt_digest": model.causal_evidence_receipt_digest,
            "evidence_grade": model.evidence_grade.value,
            "gain": model.gain,
            "interval_radius": model.interval_radius,
            "learned_through": model.learned_through.astimezone(UTC).isoformat(),
            "link_path": model.link_path,
            "mean_absolute_error": model.mean_absolute_error,
            "model_id": model.model_id,
            "offset": model.offset,
            "propagation_lag_seconds": model.propagation_lag_seconds,
            "revision": model.revision,
            "sample_count": model.sample_count,
            "source_type": model.source_type,
            "status": model.status.value,
            "target_metric": model.target_metric,
            "target_type": model.target_type,
            "trigger_ref": model.trigger_ref,
            "version": model.version,
        }
    )


def graph_effect_model_slot_digest(model: GraphEffectModel) -> str:
    """Identify the one active slot shared by equivalent model revisions."""

    return _content_digest(
        {
            "link_path": model.link_path,
            "source_type": model.source_type,
            "target_metric": model.target_metric,
            "target_type": model.target_type,
            "trigger_ref": model.trigger_ref,
        }
    )


def validate_graph_model_promotion(
    *,
    receipt: GraphModelPromotionReceipt,
    model: GraphEffectModel,
    current_pointer: GraphModelActivePointer | None,
    expected_ontology_release_digest: str,
    expected_property_semantics_digest: str,
    policy: GraphModelPromotionPolicy,
) -> None:
    """Reject stale, mismatched, or insufficient evidence before pointer mutation."""

    if model.status is not EffectModelStatus.CHALLENGER:
        raise ValueError("only a challenger graph effect model can be promoted")
    if (
        receipt.model_ref != model.ref
        or receipt.model_digest != graph_effect_model_digest(model)
        or receipt.slot_digest != graph_effect_model_slot_digest(model)
        or receipt.causal_receipt_digest != model.causal_evidence_receipt_digest
        or receipt.evidence_grade is not model.evidence_grade
    ):
        raise ValueError("graph model promotion receipt does not match its immutable model")
    if (
        receipt.ontology_release_digest != expected_ontology_release_digest
        or receipt.property_semantics_digest != expected_property_semantics_digest
    ):
        raise ValueError("graph model promotion semantic release mismatched")
    current_revision = current_pointer.revision if current_pointer is not None else 0
    current_ref = current_pointer.active_model_ref if current_pointer is not None else None
    current_digest = current_pointer.active_model_digest if current_pointer is not None else None
    if (
        receipt.expected_pointer_revision != current_revision
        or receipt.rollback_model_ref != current_ref
        or receipt.rollback_model_digest != current_digest
    ):
        raise ValueError("graph model promotion receipt is stale")
    minimum_grade = policy.min_evidence_grade
    if receipt.risk is GraphModelRisk.HIGH and policy.require_interventional_for_high_risk:
        minimum_grade = CausalEvidenceGrade.INTERVENTIONAL
    if _EVIDENCE_RANK[receipt.evidence_grade] < _EVIDENCE_RANK[minimum_grade]:
        raise ValueError("graph model promotion causal evidence is insufficient")
    if (
        receipt.sample_count < policy.min_samples
        or receipt.fidelity < policy.min_fidelity
        or not receipt.recurrence_window_complete
        or receipt.recurrence_rate > policy.max_recurrence_rate
        or receipt.policy_escapes > policy.max_policy_escapes
    ):
        raise ValueError("graph model promotion policy evidence failed")


def _content_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_digest(value: str, name: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be SHA-256")


def _validate_optional_model_identity(
    model_ref: str | None,
    model_digest: str | None,
    name: str,
) -> None:
    if (model_ref is None) != (model_digest is None):
        raise ValueError(f"{name} ref and digest MUST be present together")
    if model_ref is not None and (not model_ref or model_digest is None):
        raise ValueError(f"{name} is invalid")
    if model_digest is not None:
        _require_digest(model_digest, name)


__all__ = [
    "GraphModelActivePointer",
    "GraphModelEvidenceCohort",
    "GraphModelPromotionPolicy",
    "GraphModelPromotionReceipt",
    "GraphModelRisk",
    "graph_effect_model_digest",
    "graph_effect_model_slot_digest",
    "validate_graph_model_promotion",
]
