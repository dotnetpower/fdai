"""Content-free contracts for per-turn ChatOps qualification observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
    QualityItemMeasurement,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ObservationAvailability(StrEnum):
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class QualificationDimensionObservation:
    """One measured value or an explicit reason why that value is unavailable."""

    dimension: QualityDimension
    availability: ObservationAvailability
    value: float | None
    reason_code: str
    evidence_ref_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_code.strip() or len(self.reason_code) > 128:
            raise ValueError("observation reason_code MUST contain 1-128 characters")
        if self.availability is ObservationAvailability.MEASURED:
            if self.value is None or not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
                raise ValueError("measured observation value MUST be finite and in [0, 1]")
        elif self.value is not None:
            raise ValueError("unavailable observation MUST NOT contain a value")
        if len(self.evidence_ref_digests) > 64 or any(
            not _is_sha256(value) for value in self.evidence_ref_digests
        ):
            raise ValueError("evidence_ref_digests MUST contain bounded SHA-256 values")
        if self.availability is ObservationAvailability.MEASURED and not self.evidence_ref_digests:
            raise ValueError("measured observation MUST cite evidence commitments")


@dataclass(frozen=True, slots=True)
class QualificationDimensionContribution:
    """One evidence-owning workstream's measured contribution to a case."""

    case_id: str
    item_id: int
    workstream: str
    metric: str
    dimension: QualityDimension
    value: float
    reason_code: str
    evidence_ref_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.case_id) is None:
            raise ValueError("contribution case_id MUST be a bounded portable token")
        if not 1 <= self.item_id <= 50:
            raise ValueError("contribution item_id MUST be in [1, 50]")
        item = CHATOPS_QUALITY_CONTRACT_V1.items[self.item_id - 1]
        if self.workstream != item.workstream or self.metric != item.metric:
            raise ValueError("contribution workstream and metric MUST match the installed contract")
        QualificationDimensionObservation(
            dimension=self.dimension,
            availability=ObservationAvailability.MEASURED,
            value=self.value,
            reason_code=self.reason_code,
            evidence_ref_digests=self.evidence_ref_digests,
        )


@dataclass(frozen=True, slots=True)
class QualificationRubricObservation:
    """Six dimension slots for one fixed ChatOps quality item."""

    item_id: int
    metric: str
    dimensions: tuple[QualificationDimensionObservation, ...]

    def __post_init__(self) -> None:
        if not 1 <= self.item_id <= 50:
            raise ValueError("rubric observation item_id MUST be in [1, 50]")
        expected_metric = CHATOPS_QUALITY_CONTRACT_V1.items[self.item_id - 1].metric
        if self.metric != expected_metric:
            raise ValueError("rubric observation metric does not match the installed contract")
        if tuple(item.dimension for item in self.dimensions) != tuple(QualityDimension):
            raise ValueError("rubric observation MUST define every quality dimension in enum order")

    def to_measurement(self) -> QualityItemMeasurement | None:
        """Return a score input only when every dimension has measured evidence."""

        if any(
            dimension.availability is ObservationAvailability.UNAVAILABLE
            for dimension in self.dimensions
        ):
            return None
        return QualityItemMeasurement(
            item_id=self.item_id,
            components=tuple(
                (dimension.dimension, _measured_value(dimension)) for dimension in self.dimensions
            ),
        )


@dataclass(frozen=True, slots=True)
class TurnQualificationObservation:
    """Content-free 50-item observation envelope for one completed turn."""

    case_id: str
    turn_digest: str
    conversation_digest: str
    principal_scope_digest: str
    question_digest: str
    answer_digest: str
    evidence_manifest_digest: str
    assessment_digest: str
    verification_route_digest: str | None
    locale: str
    items: tuple[QualificationRubricObservation, ...]

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.case_id) is None:
            raise ValueError("case_id MUST be a bounded portable token")
        for name, value in (
            ("turn_digest", self.turn_digest),
            ("conversation_digest", self.conversation_digest),
            ("principal_scope_digest", self.principal_scope_digest),
            ("question_digest", self.question_digest),
            ("answer_digest", self.answer_digest),
            ("evidence_manifest_digest", self.evidence_manifest_digest),
            ("assessment_digest", self.assessment_digest),
        ):
            if not _is_sha256(value):
                raise ValueError(f"{name} MUST be a lowercase SHA-256 digest")
        if self.verification_route_digest is not None and not _is_sha256(
            self.verification_route_digest
        ):
            raise ValueError("verification_route_digest MUST be a lowercase SHA-256 digest")
        if self.locale not in {"en", "ko"}:
            raise ValueError("observation locale MUST be en or ko")
        if tuple(item.item_id for item in self.items) != tuple(range(1, 51)):
            raise ValueError("turn observation MUST contain item ids 1 through 50 in order")

    def complete_measurements(self) -> tuple[QualityItemMeasurement, ...]:
        """Return only items whose six dimensions are independently measured."""

        return tuple(
            measurement for item in self.items if (measurement := item.to_measurement()) is not None
        )

    def to_dict(self) -> dict[str, object]:
        """Return a stable content-addressed record without raw runtime identifiers."""

        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "chatops_turn_qualification_observation",
            "qualification_authority": False,
            "case_id": self.case_id,
            "turn_digest": self.turn_digest,
            "conversation_digest": self.conversation_digest,
            "principal_scope_digest": self.principal_scope_digest,
            "question_digest": self.question_digest,
            "answer_digest": self.answer_digest,
            "evidence_manifest_digest": self.evidence_manifest_digest,
            "assessment_digest": self.assessment_digest,
            "verification_route_digest": self.verification_route_digest,
            "locale": self.locale,
            "items": [
                {
                    "item_id": item.item_id,
                    "metric": item.metric,
                    "dimensions": [
                        {
                            "dimension": dimension.dimension.value,
                            "availability": dimension.availability.value,
                            "value": dimension.value,
                            "reason_code": dimension.reason_code,
                            "evidence_ref_digests": list(dimension.evidence_ref_digests),
                        }
                        for dimension in item.dimensions
                    ],
                }
                for item in self.items
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload["content_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
        return payload


def _measured_value(observation: QualificationDimensionObservation) -> float:
    if observation.value is None:
        raise ValueError("measured observation is missing its value")
    return observation.value


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ObservationAvailability",
    "QualificationDimensionContribution",
    "QualificationDimensionObservation",
    "QualificationRubricObservation",
    "TurnQualificationObservation",
]
