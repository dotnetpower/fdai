"""Contracts for resilience scheduling, execution, and evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.dr_experiment import DrRunHandle, DrRunStatus


class SchedulerOutcome(StrEnum):
    ALLOWED = "allowed"
    OUTSIDE_WINDOW = "outside_window"
    FROZEN = "frozen"
    OPT_OUT = "opt_out"
    CONCURRENCY_CAP = "concurrency_cap"


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class FreezePeriod:
    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class DrExperiment:
    experiment_id: str
    target_resource_ref: str
    target_resource_tags: frozenset[str] = field(default_factory=frozenset)
    scheduled_at: datetime | None = None
    provider_ref: str | None = None
    is_production_target: bool = False
    has_rollback_path: bool = False
    stop_conditions: tuple[str, ...] = ()


class ExecutionMode(StrEnum):
    SHADOW = "shadow"
    ENFORCE = "enforce"


class RunOutcome(StrEnum):
    NOT_ALLOWED = "not_allowed"
    ISOLATION_VIOLATION = "isolation_violation"
    MISSING_ROLLBACK_PATH = "missing_rollback_path"
    MISSING_STOP_CONDITION = "missing_stop_condition"
    MISSING_PROVIDER_REF = "missing_provider_ref"
    RUNNER_NOT_CONFIGURED = "runner_not_configured"
    SHADOW_LOGGED = "shadow_logged"
    EXECUTED = "executed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class DrSchedulerConfig:
    max_concurrent_experiments: int = 1
    opt_out_tag: str = "chaos:opt-out"


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    experiment_id: str
    outcome: SchedulerOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DrRunResult:
    experiment_id: str
    outcome: RunOutcome
    decision: SchedulerDecision
    handle: DrRunHandle | None = None
    status: DrRunStatus | None = None
    error: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime | None = None
