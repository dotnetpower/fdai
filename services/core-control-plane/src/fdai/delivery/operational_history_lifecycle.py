"""Plan bounded scheduled operational-history lifecycle work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionPin,
    ObservationPartitionState,
    active_partition_pins,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
    StoragePressureLevel,
)
from fdai.core.scheduler.models import ScheduledTask, ScheduleKind


class OperationalHistoryLifecycleAction(StrEnum):
    """One deterministic next action for a lifecycle coordinator."""

    SEAL = "seal"
    CHECKPOINT = "checkpoint"
    ARCHIVE = "archive"
    VERIFY = "verify"
    RESTORE_SAMPLE = "restore_sample"
    HOLD = "hold"
    MARK_PURGE_ELIGIBLE = "mark_purge_eligible"
    PURGE = "purge"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class OperationalHistoryLifecycleEvidence:
    """Current durable gates for one partition."""

    checkpoint: ObservationCheckpoint | None
    archive_written: bool
    archive_verified: bool
    restore_passed: bool
    retention_permitted: bool
    correction_closed: bool
    pins: tuple[ObservationPartitionPin, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationalHistoryLifecycleDecision:
    """Bounded next action with explicit blockers."""

    partition_id: str
    action: OperationalHistoryLifecycleAction
    target_state: ObservationPartitionState
    reason_codes: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("operational history lifecycle decision grants no authority")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("operational history lifecycle reasons MUST be sorted and unique")


def plan_operational_history_lifecycle(
    partition: ObservationPartition,
    evidence: OperationalHistoryLifecycleEvidence,
    pressure: StoragePressureAssessment,
    *,
    now: datetime,
) -> OperationalHistoryLifecycleDecision:
    """Choose one monotonic lifecycle action without performing I/O."""

    active_pins = active_partition_pins(evidence.pins, at=now)
    if active_pins or not evidence.retention_permitted:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.HOLD,
            ObservationPartitionState.HELD,
            ("partition_pin_active" if active_pins else "retention_hold_active",),
        )
    if (
        partition.state is ObservationPartitionState.CORRECTION_PENDING
        and not evidence.correction_closed
    ):
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.HOLD,
            ObservationPartitionState.CORRECTION_PENDING,
            ("correction_pending",),
        )
    if partition.state is ObservationPartitionState.OPEN:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.SEAL,
            ObservationPartitionState.SEALED,
        )
    if partition.state is ObservationPartitionState.SEALED:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.CHECKPOINT,
            ObservationPartitionState.CHECKPOINTED,
            () if evidence.checkpoint is not None else ("checkpoint_required",),
        )
    if partition.state is ObservationPartitionState.CHECKPOINTED:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.ARCHIVE,
            ObservationPartitionState.ARCHIVED,
            () if evidence.archive_written else ("archive_write_required",),
        )
    if partition.state is ObservationPartitionState.ARCHIVED:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.VERIFY,
            ObservationPartitionState.VERIFIED,
            () if evidence.archive_verified else ("archive_verification_required",),
        )
    if partition.state is ObservationPartitionState.VERIFIED:
        if not evidence.restore_passed:
            return _decision(
                partition,
                OperationalHistoryLifecycleAction.RESTORE_SAMPLE,
                ObservationPartitionState.VERIFIED,
                ("restore_sample_required",),
            )
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.MARK_PURGE_ELIGIBLE,
            ObservationPartitionState.PURGE_ELIGIBLE,
        )
    if partition.state is ObservationPartitionState.PURGE_ELIGIBLE:
        return _decision(
            partition,
            OperationalHistoryLifecycleAction.PURGE,
            ObservationPartitionState.PURGED,
            (("storage_pressure_hard",) if pressure.level is StoragePressureLevel.HARD else ()),
        )
    return _decision(
        partition,
        OperationalHistoryLifecycleAction.NONE,
        partition.state,
    )


def operational_history_lifecycle_schedule(
    *,
    interval_seconds: int = 3600,
) -> ScheduledTask:
    """Return the fixed shadow scheduler definition for lifecycle coordination."""

    return ScheduledTask(
        task_id="operational-history-lifecycle",
        name="Operational history lifecycle",
        interval_seconds=interval_seconds,
        event_type="operational_history.lifecycle_due",
        created_by="system:operational-history-lifecycle",
        event_payload={
            "schema_version": "1.0.0",
            "mode": "shadow",
            "execution_authority": False,
        },
        schedule_kind=ScheduleKind.INTERVAL,
    )


def _decision(
    partition: ObservationPartition,
    action: OperationalHistoryLifecycleAction,
    state: ObservationPartitionState,
    reasons: tuple[str, ...] = (),
) -> OperationalHistoryLifecycleDecision:
    return OperationalHistoryLifecycleDecision(
        partition_id=partition.partition_id,
        action=action,
        target_state=state,
        reason_codes=tuple(sorted(reasons)),
    )


__all__ = [
    "OperationalHistoryLifecycleAction",
    "OperationalHistoryLifecycleDecision",
    "OperationalHistoryLifecycleEvidence",
    "operational_history_lifecycle_schedule",
    "plan_operational_history_lifecycle",
]
