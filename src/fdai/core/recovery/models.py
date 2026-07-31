"""Immutable recovery planning and verification contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.ontology_instance import OntologyObjectRecord


class RecoveryStrategy(StrEnum):
    ROLLBACK = "rollback"
    COMPENSATE = "compensate"
    STATE_FORWARD = "state_forward"
    FAILOVER = "failover"
    RESTORE = "restore"


class RecoveryPlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    STALE = "stale"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    action_id: str
    action_type_ref: str
    action_type_version: str
    target_ref: str
    depends_on: tuple[str, ...] = ()
    compensation_action_type_ref: str | None = None
    stop_conditions: tuple[str, ...] = ()
    rollback_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("action_id", self.action_id),
            ("action_type_ref", self.action_type_ref),
            ("action_type_version", self.action_type_version),
            ("target_ref", self.target_ref),
        ):
            if not value.strip():
                raise ValueError(f"{name} MUST be non-empty")
        if any(not item.strip() for item in (*self.depends_on, *self.stop_conditions)):
            raise ValueError("recovery dependencies and stop conditions MUST be non-empty")


@dataclass(frozen=True, slots=True)
class RecoveryPlanRecord:
    plan_id: str
    strategy: RecoveryStrategy
    status: RecoveryPlanStatus
    workflow_ref: str
    workflow_version: str
    catalog_digest: str
    actions: tuple[RecoveryAction, ...]
    compensation_order: tuple[str, ...]
    impact_envelope_id: str
    recovery_objective_ref: str
    verification_probes: tuple[str, ...]
    direct_target_ids: tuple[str, ...]
    graph_revision: str
    dry_run_receipt: str
    last_rehearsed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("plan_id", self.plan_id),
            ("workflow_ref", self.workflow_ref),
            ("workflow_version", self.workflow_version),
            ("catalog_digest", self.catalog_digest),
            ("impact_envelope_id", self.impact_envelope_id),
            ("recovery_objective_ref", self.recovery_objective_ref),
            ("graph_revision", self.graph_revision),
            ("dry_run_receipt", self.dry_run_receipt),
        ):
            if not value.strip():
                raise ValueError(f"{name} MUST be non-empty")
        if not self.actions or not self.verification_probes or not self.direct_target_ids:
            raise ValueError("recovery actions, probes, and targets MUST be non-empty")
        if self.last_rehearsed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("recovery plan timestamps MUST be timezone-aware")
        action_ids = {item.action_id for item in self.actions}
        if set(self.compensation_order) != action_ids:
            raise ValueError("compensation_order MUST contain every recovery action exactly once")

    def to_ontology_object(self) -> OntologyObjectRecord:
        return OntologyObjectRecord(
            id=self.plan_id,
            object_type="RecoveryPlan",
            properties={
                "id": self.plan_id,
                "strategy": self.strategy.value,
                "status": self.status.value,
                "workflow_ref": f"{self.workflow_ref}@{self.workflow_version}",
                "action_type_refs": [
                    f"{item.action_type_ref}@{item.action_type_version}" for item in self.actions
                ],
                "compensation_order": list(self.compensation_order),
                "impact_envelope_id": self.impact_envelope_id,
                "recovery_objective_ref": self.recovery_objective_ref,
                "verification_probes": list(self.verification_probes),
                "last_rehearsed_at": self.last_rehearsed_at,
                "expires_at": self.expires_at,
            },
        )


@dataclass(frozen=True, slots=True)
class RecoveryReadiness:
    ready: bool
    reasons: tuple[str, ...]


class RecoveryProbeKind(StrEnum):
    FAULT_ABSENT = "fault_absent"
    TARGET_HEALTHY = "target_healthy"
    OBJECTIVES_RECOVERED = "objectives_recovered"
    INDIRECT_SYMPTOMS_ABSENT = "indirect_symptoms_absent"
    COMPENSATION_COMPLETE = "compensation_complete"
    RECURRENCE_CLEAR = "recurrence_clear"


class ProbeVerdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RecoveryProbeResult:
    kind: RecoveryProbeKind
    verdict: ProbeVerdict
    observed_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or not self.evidence_ref.strip():
            raise ValueError("probe evidence and timezone-aware timestamp are required")


class RecoveryVerificationOutcome(StrEnum):
    RECOVERED = "recovered"
    PARTIALLY_RECOVERED = "partially_recovered"
    NOT_RECOVERED = "not_recovered"
    UNSCORABLE = "unscorable"


@dataclass(frozen=True, slots=True)
class RecoveryVerification:
    outcome: RecoveryVerificationOutcome
    probe_results: tuple[RecoveryProbeResult, ...]
    telemetry_complete: bool
    reason: str


__all__ = [
    "ProbeVerdict",
    "RecoveryAction",
    "RecoveryPlanRecord",
    "RecoveryPlanStatus",
    "RecoveryProbeKind",
    "RecoveryProbeResult",
    "RecoveryReadiness",
    "RecoveryStrategy",
    "RecoveryVerification",
    "RecoveryVerificationOutcome",
]
