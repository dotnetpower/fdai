"""Resilience vertical - DR / chaos scheduling and DB DR drill runner.

Phase 3 § Resilience. This subpackage groups:

- :mod:`.orchestrator` - :class:`DrExperiment`, :class:`DrScheduler`,
  :class:`DrRunReport`, :class:`DrObjective`, :func:`summarize_runs`,
  and the maintenance-window / freeze-period vocabulary that shapes
  which experiments may run when.
- :mod:`.db_dr_verifier` - post-drill parity / RPO / RTO verification.
- :mod:`.db_dr_drill_cli` - operator-facing CLI harness for scheduled
  DR drills.

Every symbol below is re-exported at the package facade so callers
continue to write ``from fdai.core.verticals.resilience import
DrExperiment`` unchanged after G-6 (tracker #14, issue #20).
"""

from __future__ import annotations

from fdai.core.verticals.resilience.db_dr_verifier import (
    DbDrOutcome,
    DbDrVerdict,
    DbDrVerifier,
)
from fdai.core.verticals.resilience.orchestrator import (
    DrExperiment,
    DrObjective,
    DrObjectiveReport,
    DrRunReport,
    DrRunResult,
    DrScheduler,
    DrSchedulerConfig,
    ExecutionMode,
    FreezePeriod,
    MaintenanceWindow,
    RunOutcome,
    SchedulerDecision,
    SchedulerOutcome,
    summarize_runs,
)
from fdai.core.verticals.resilience.recovery_coordinator import (
    RecoveryApprovalError,
    RecoveryCoordinatorError,
    RecoveryPlanCoordinator,
    RecoveryPlanRecord,
    RecoveryRecordError,
    RecoveryWriteConflictError,
)
from fdai.core.verticals.resilience.recovery_plan import (
    LEGAL_RECOVERY_TRANSITIONS,
    RecoveryMode,
    RecoveryObjectives,
    RecoveryPlan,
    RecoveryPlanError,
    RecoveryPlanStateMachine,
    RecoveryProfile,
    RecoveryState,
    RecoveryTransition,
)

__all__ = [
    "DbDrOutcome",
    "DbDrVerdict",
    "DbDrVerifier",
    "DrExperiment",
    "DrObjective",
    "DrObjectiveReport",
    "DrRunReport",
    "DrRunResult",
    "DrScheduler",
    "DrSchedulerConfig",
    "ExecutionMode",
    "FreezePeriod",
    "MaintenanceWindow",
    "LEGAL_RECOVERY_TRANSITIONS",
    "RecoveryApprovalError",
    "RecoveryCoordinatorError",
    "RecoveryMode",
    "RecoveryObjectives",
    "RecoveryPlan",
    "RecoveryPlanCoordinator",
    "RecoveryPlanError",
    "RecoveryPlanRecord",
    "RecoveryPlanStateMachine",
    "RecoveryProfile",
    "RecoveryState",
    "RecoveryTransition",
    "RecoveryRecordError",
    "RecoveryWriteConflictError",
    "RunOutcome",
    "SchedulerDecision",
    "SchedulerOutcome",
    "summarize_runs",
]
