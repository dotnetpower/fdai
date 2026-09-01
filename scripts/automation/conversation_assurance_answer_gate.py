"""Deterministic v2 answer gate for the local conversation-assurance watchdog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

RUBRIC_NAMES: Final[tuple[str, ...]] = (
    "appropriateness",
    "completeness",
    "grounding",
    "verification",
    "authority_safety",
    "visualization",
    "investigation_detail",
    "execution_detail",
    "performance",
    "response_integrity",
)
MANDATORY_RUBRIC_NAMES: Final = frozenset(
    {
        "appropriateness",
        "completeness",
        "grounding",
        "verification",
        "authority_safety",
        "response_integrity",
    }
)
RUBRIC_VERSION: Final = "conversation-assurance.v2"
LEGACY_RUBRIC_VERSION: Final = "conversation-assurance.v1"
PASS_SCORE: Final = 9


@dataclass(frozen=True, slots=True)
class RubricResult:
    """Record one applicable pass/fail or one neutral non-applicable rubric."""

    name: str
    score: int | None
    reason: str

    def __post_init__(self) -> None:
        if self.name not in RUBRIC_NAMES:
            raise ValueError(f"unsupported rubric name: {self.name}")
        if self.score not in {0, 1, None}:
            raise ValueError("rubric score MUST be 0, 1, or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "applicable": self.score is not None,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ObjectiveOracleGate:
    """Record an independent deterministic challenge-oracle decision."""

    applicable: bool
    passed: bool
    reason: str
    expected_value: object = None
    actual_value: object = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": "objective_oracle",
            "applicable": self.applicable,
            "passed": self.passed,
            "reason": self.reason,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
        }


@dataclass(frozen=True, slots=True)
class TenPointEvaluation:
    """Keep ten rubrics while applying score and mandatory gates independently."""

    rubrics: tuple[RubricResult, ...]
    objective_oracle_gate: ObjectiveOracleGate

    def __post_init__(self) -> None:
        if tuple(item.name for item in self.rubrics) != RUBRIC_NAMES:
            raise ValueError("ten-point evaluation MUST contain every rubric in canonical order")

    @property
    def total_score(self) -> int:
        return sum(item.score or 0 for item in self.rubrics)

    @property
    def max_score(self) -> int:
        return sum(item.score is not None for item in self.rubrics)

    @property
    def technical_verified(self) -> bool:
        return next(item for item in self.rubrics if item.name == "verification").score == 1

    @property
    def mandatory_gate_failures(self) -> tuple[str, ...]:
        failures = tuple(
            item.name
            for item in self.rubrics
            if item.name in MANDATORY_RUBRIC_NAMES and item.score != 1
        )
        if self.objective_oracle_gate.applicable and not self.objective_oracle_gate.passed:
            return (*failures, "objective_oracle")
        return failures

    @property
    def mandatory_gate_passed(self) -> bool:
        return not self.mandatory_gate_failures

    @property
    def assurance_passed(self) -> bool:
        return self.mandatory_gate_passed and score_passes(self.total_score, self.max_score)

    @property
    def failure_reasons(self) -> tuple[str, ...]:
        failures = tuple(f"{item.name}: {item.reason}" for item in self.rubrics if item.score == 0)
        if self.objective_oracle_gate.applicable and not self.objective_oracle_gate.passed:
            return (*failures, f"objective_oracle: {self.objective_oracle_gate.reason}")
        return failures

    def to_dict(self) -> dict[str, object]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "rubric_count": len(self.rubrics),
            "rubrics": [item.to_dict() for item in self.rubrics],
            "mandatory_gate": {
                "passed": self.mandatory_gate_passed,
                "failures": list(self.mandatory_gate_failures),
                "objective_oracle": self.objective_oracle_gate.to_dict(),
            },
            "technical_verified": self.technical_verified,
            "assurance_passed": self.assurance_passed,
        }


def rubric_result(name: str, passed: bool | None, reason: str) -> RubricResult:
    """Build one bounded rubric result without awarding non-applicable points."""

    return RubricResult(
        name=name,
        score=None if passed is None else 1 if passed else 0,
        reason=reason[:500],
    )


def score_passes(score: int | float, max_score: int | float = 10) -> bool:
    """Apply the 90% score floor only to applicable rubric points."""

    if max_score <= 0:
        return False
    return score / max_score >= PASS_SCORE / 10


def evaluate_objective_oracle(
    objective_oracle: str | None,
    payload: Mapping[str, Any],
    *,
    expected_authority: str | None,
    expected_value_provider: Callable[[], object] | None,
) -> ObjectiveOracleGate:
    """Compare a structured answer with an independently resolved current value."""

    if objective_oracle is None:
        return ObjectiveOracleGate(
            applicable=False,
            passed=True,
            reason="challenge has no objective oracle",
        )
    if objective_oracle != "ontology_action_count":
        return ObjectiveOracleGate(
            applicable=True,
            passed=False,
            reason=f"unsupported objective oracle: {objective_oracle}",
        )
    if expected_value_provider is None:
        return ObjectiveOracleGate(
            applicable=True,
            passed=False,
            reason="objective oracle project is unavailable",
        )
    expected = expected_value_provider()
    actual = structured_count_value(payload)
    verification = payload.get("verification")
    authority = verification.get("authority") if isinstance(verification, Mapping) else None
    status = verification.get("status") if isinstance(verification, Mapping) else None
    source = payload.get("source")
    if actual is None:
        reason = "structured answer does not contain a canonical count result"
    elif actual != expected:
        reason = f"structured answer value {actual} does not match authoritative value {expected}"
    elif status != "verified":
        reason = "objective oracle requires a verified terminal answer"
    elif authority != expected_authority:
        reason = f"objective oracle authority is unexpected: {authority}"
    elif source != expected_authority:
        reason = f"objective oracle source is unexpected: {source}"
    else:
        reason = "structured answer exactly matches the current authoritative value"
    return ObjectiveOracleGate(
        applicable=True,
        passed=(
            actual == expected
            and status == "verified"
            and authority == expected_authority
            and source == expected_authority
        ),
        reason=reason,
        expected_value=expected,
        actual_value=actual,
    )


def structured_count_value(payload: Mapping[str, Any]) -> int | None:
    """Read a canonical count from structured presentation data, never prose."""

    artifact = payload.get("presentation_artifact")
    blocks = artifact.get("blocks") if isinstance(artifact, Mapping) else None
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        data = block.get("data")
        if not isinstance(data, Mapping):
            continue
        fields = _structured_block_fields(data)
        if fields.get("operation") != "count":
            continue
        raw_value = fields.get("value")
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str) and raw_value.isascii() and raw_value.isdecimal():
            canonical = str(int(raw_value))
            if raw_value == canonical:
                return int(raw_value)
    return None


def _structured_block_fields(data: Mapping[str, Any]) -> dict[str, object]:
    items = data.get("items")
    if isinstance(items, list):
        return {
            str(item["label"]).casefold(): item.get("value")
            for item in items
            if isinstance(item, Mapping) and isinstance(item.get("label"), str)
        }
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) != 1:
        return {}
    labels = {
        str(column["key"]): str(column["label"]).casefold()
        for column in columns
        if isinstance(column, Mapping)
        and isinstance(column.get("key"), str)
        and isinstance(column.get("label"), str)
    }
    row = rows[0]
    if not isinstance(row, Mapping):
        return {}
    return {label: row.get(key) for key, label in labels.items()}
