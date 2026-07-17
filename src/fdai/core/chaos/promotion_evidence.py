"""Append-only evidence state machine for chaos-scenario promotion."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ScenarioPromotionState(StrEnum):
    COLLECTED = "collected"
    SHADOW_VALIDATED = "shadow_validated"
    APPROVAL_PENDING = "approval_pending"
    ENFORCE_ELIGIBLE = "enforce_eligible"
    REGRESSED = "regressed"


@dataclass(frozen=True, slots=True)
class ScenarioEvidenceKey:
    scenario_id: str
    scenario_version: int
    catalog_fingerprint: str

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id MUST be non-empty")
        if self.scenario_version < 1:
            raise ValueError("scenario_version MUST be positive")
        if not _SHA256.fullmatch(self.catalog_fingerprint):
            raise ValueError("catalog_fingerprint MUST be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class ScenarioPromotionEvidence:
    evidence_id: str
    key: ScenarioEvidenceKey
    from_state: ScenarioPromotionState
    to_state: ScenarioPromotionState
    actor_principal: str
    audit_ref: str
    observed_at: datetime
    runner_version: str
    stop_condition_observed: bool | None = None
    rollback_succeeded: bool | None = None
    blast_radius_compliant: bool | None = None
    detection_latency_ms: int | None = None
    latency_budget_ms: int | None = None
    approval_ref: str | None = None
    approval_principal: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("evidence_id", self.evidence_id),
            ("actor_principal", self.actor_principal),
            ("audit_ref", self.audit_ref),
            ("runner_version", self.runner_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at MUST be timezone-aware")
        if self.detection_latency_ms is not None and self.detection_latency_ms < 0:
            raise ValueError("detection_latency_ms MUST be non-negative")
        if self.latency_budget_ms is not None and self.latency_budget_ms < 1:
            raise ValueError("latency_budget_ms MUST be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "scenario_id": self.key.scenario_id,
            "scenario_version": self.key.scenario_version,
            "catalog_fingerprint": self.key.catalog_fingerprint,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "actor_principal": self.actor_principal,
            "audit_ref": self.audit_ref,
            "observed_at": self.observed_at.isoformat(),
            "runner_version": self.runner_version,
            "stop_condition_observed": self.stop_condition_observed,
            "rollback_succeeded": self.rollback_succeeded,
            "blast_radius_compliant": self.blast_radius_compliant,
            "detection_latency_ms": self.detection_latency_ms,
            "latency_budget_ms": self.latency_budget_ms,
            "approval_ref": self.approval_ref,
            "approval_principal": self.approval_principal,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ScenarioPromotionEvidence:
        if raw.get("schema_version") != 1:
            raise ScenarioPromotionError("unsupported promotion evidence schema_version")
        try:
            return cls(
                evidence_id=str(raw["evidence_id"]),
                key=ScenarioEvidenceKey(
                    scenario_id=str(raw["scenario_id"]),
                    scenario_version=int(raw["scenario_version"]),
                    catalog_fingerprint=str(raw["catalog_fingerprint"]),
                ),
                from_state=ScenarioPromotionState(str(raw["from_state"])),
                to_state=ScenarioPromotionState(str(raw["to_state"])),
                actor_principal=str(raw["actor_principal"]),
                audit_ref=str(raw["audit_ref"]),
                observed_at=datetime.fromisoformat(str(raw["observed_at"])),
                runner_version=str(raw["runner_version"]),
                stop_condition_observed=_optional_bool(raw.get("stop_condition_observed")),
                rollback_succeeded=_optional_bool(raw.get("rollback_succeeded")),
                blast_radius_compliant=_optional_bool(raw.get("blast_radius_compliant")),
                detection_latency_ms=_optional_int(raw.get("detection_latency_ms")),
                latency_budget_ms=_optional_int(raw.get("latency_budget_ms")),
                approval_ref=_optional_str(raw.get("approval_ref")),
                approval_principal=_optional_str(raw.get("approval_principal")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScenarioPromotionError("malformed promotion evidence record") from exc


class ScenarioPromotionError(ValueError):
    """Raised when evidence cannot advance the fail-closed state machine."""


class ScenarioPromotionLedger:
    """In-memory projection over append-only promotion evidence records."""

    def __init__(self) -> None:
        self._records: list[ScenarioPromotionEvidence] = []
        self._states: dict[ScenarioEvidenceKey, ScenarioPromotionState] = {}
        self._evidence_ids: set[str] = set()

    @property
    def records(self) -> tuple[ScenarioPromotionEvidence, ...]:
        return tuple(self._records)

    def state_for(self, key: ScenarioEvidenceKey) -> ScenarioPromotionState:
        return self._states.get(key, ScenarioPromotionState.COLLECTED)

    def append(self, evidence: ScenarioPromotionEvidence) -> ScenarioPromotionState:
        if evidence.evidence_id in self._evidence_ids:
            raise ScenarioPromotionError("duplicate evidence_id")
        current = self.state_for(evidence.key)
        if evidence.from_state is not current:
            raise ScenarioPromotionError("evidence from_state does not match current state")
        self._validate_transition(evidence)
        self._records.append(evidence)
        self._evidence_ids.add(evidence.evidence_id)
        self._states[evidence.key] = evidence.to_state
        return evidence.to_state

    def is_enforce_eligible(self, key: ScenarioEvidenceKey) -> bool:
        return self.state_for(key) is ScenarioPromotionState.ENFORCE_ELIGIBLE

    def approval_ref_for(self, key: ScenarioEvidenceKey) -> str | None:
        if not self.is_enforce_eligible(key):
            return None
        return next(
            (
                record.approval_ref
                for record in reversed(self._records)
                if record.key == key and record.to_state is ScenarioPromotionState.ENFORCE_ELIGIBLE
            ),
            None,
        )

    def _validate_transition(self, evidence: ScenarioPromotionEvidence) -> None:
        transition = (evidence.from_state, evidence.to_state)
        allowed = {
            (ScenarioPromotionState.COLLECTED, ScenarioPromotionState.SHADOW_VALIDATED),
            (ScenarioPromotionState.REGRESSED, ScenarioPromotionState.SHADOW_VALIDATED),
            (ScenarioPromotionState.SHADOW_VALIDATED, ScenarioPromotionState.APPROVAL_PENDING),
            (ScenarioPromotionState.APPROVAL_PENDING, ScenarioPromotionState.ENFORCE_ELIGIBLE),
            (ScenarioPromotionState.ENFORCE_ELIGIBLE, ScenarioPromotionState.REGRESSED),
        }
        if transition not in allowed:
            raise ScenarioPromotionError("invalid promotion transition")
        if evidence.to_state is ScenarioPromotionState.SHADOW_VALIDATED:
            self._validate_shadow_evidence(evidence)
        elif evidence.to_state is ScenarioPromotionState.APPROVAL_PENDING:
            if evidence.actor_principal != "Mimir":
                raise ScenarioPromotionError("only Mimir may request scenario approval")
        elif evidence.to_state is ScenarioPromotionState.ENFORCE_ELIGIBLE:
            if evidence.actor_principal != "Mimir":
                raise ScenarioPromotionError("only Mimir may mark enforce eligibility")
            if not evidence.approval_ref or evidence.approval_principal != "Var":
                raise ScenarioPromotionError("Var HIL approval is required")
        elif evidence.to_state is ScenarioPromotionState.REGRESSED:
            if evidence.actor_principal != "Mimir":
                raise ScenarioPromotionError("only Mimir may regress a scenario")

    @staticmethod
    def _validate_shadow_evidence(evidence: ScenarioPromotionEvidence) -> None:
        if evidence.actor_principal != "Saga":
            raise ScenarioPromotionError("only Saga may record shadow validation evidence")
        if evidence.stop_condition_observed is not True:
            raise ScenarioPromotionError("shadow evidence requires an observed stop condition")
        if evidence.rollback_succeeded is not True:
            raise ScenarioPromotionError("shadow evidence requires rollback success")
        if evidence.blast_radius_compliant is not True:
            raise ScenarioPromotionError("shadow evidence requires blast-radius compliance")
        if evidence.detection_latency_ms is None or evidence.latency_budget_ms is None:
            raise ScenarioPromotionError("shadow evidence requires latency measurement and budget")
        if evidence.detection_latency_ms > evidence.latency_budget_ms:
            raise ScenarioPromotionError("shadow evidence exceeds the latency budget")


def load_promotion_ledger(path: Path) -> ScenarioPromotionLedger:
    ledger = ScenarioPromotionLedger()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScenarioPromotionError(
                f"promotion evidence line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(raw, dict):
            raise ScenarioPromotionError(f"promotion evidence line {line_number} MUST be an object")
        ledger.append(ScenarioPromotionEvidence.from_dict(raw))
    return ledger


def _optional_bool(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeError("expected bool or null")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected int or null")
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("expected string or null")
    return value


__all__ = [
    "ScenarioEvidenceKey",
    "ScenarioPromotionError",
    "ScenarioPromotionEvidence",
    "ScenarioPromotionLedger",
    "ScenarioPromotionState",
    "load_promotion_ledger",
]
