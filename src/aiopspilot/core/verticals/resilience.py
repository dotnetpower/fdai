"""DR / Chaos scheduler — window-based test failover + measured RPO/RTO.

Phase 3 § DR / Chaos (see
[`docs/roadmap/phases/phase-3-integrated-loop.md § DR / Chaos`]).

Contract
--------

Given a scheduled :class:`DrExperiment` and the current wall-clock time,
the scheduler decides whether the experiment MAY run right now. A run
requires **all** of:

- current time falls inside an approved :class:`MaintenanceWindow`;
- current time is NOT inside a :class:`FreezePeriod`;
- the target resource does NOT carry an ``opt-out`` tag;
- the count of concurrent in-flight experiments stays under
  :attr:`DrSchedulerConfig.max_concurrent_experiments`.

The scheduler is a **pure function of its explicit inputs** — no state
mutation, no audit write, and no I/O. ``at`` MAY be omitted, in which
case the scheduler reads :func:`datetime.now(tz=UTC)` as a convenience
default so callers can fire-and-forget in production; every test in
this module supplies ``at`` explicitly so the outcome is deterministic
regardless of wall-clock. The caller (a P3 orchestrator) persists the
decision + mutates the in-flight count around the actual run.

RPO/RTO measurement
-------------------

:class:`DrRunReport` carries the **measured** RPO (data loss at failover
in seconds) and RTO (wall-clock from trigger to verified restored
service). The scheduler doesn't run experiments; it only decides *when*
they may run. Measurement is produced by the DR runner (owner: DR/Chaos
lead in [phase-3 § Open Questions]) and handed here for reporting.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median
from typing import TYPE_CHECKING, Final

from aiopspilot.shared.providers.dr_experiment import DrRunHandle, DrRunStatus

if TYPE_CHECKING:
    # ``DrExperimentRunner`` is only referenced in type annotations —
    # importing it at runtime would create no cycle, but keeping it
    # under ``TYPE_CHECKING`` documents that this module holds no
    # runtime dependency on the Protocol class itself.
    from aiopspilot.shared.providers.dr_experiment import DrExperimentRunner


class SchedulerOutcome(StrEnum):
    """One decision from :meth:`DrScheduler.decide`."""

    ALLOWED = "allowed"
    """Experiment MAY run now — window + freeze + tags + concurrency all clear."""

    OUTSIDE_WINDOW = "outside_window"
    """No approved maintenance window is active at the given time."""

    FROZEN = "frozen"
    """A freeze/quiet period overrides any window in effect."""

    OPT_OUT = "opt_out"
    """The target resource is tagged out of chaos runs."""

    CONCURRENCY_CAP = "concurrency_cap"
    """Too many experiments already in flight."""


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    """UTC time window during which DR/Chaos runs are allowed.

    Weekly windows are declared by weekday + local-time; the caller
    resolves to UTC before handing to the scheduler.
    """

    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class FreezePeriod:
    """UTC period during which no DR run is permitted (release freeze, holiday, ...)."""

    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


@dataclass(frozen=True, slots=True)
class DrExperiment:
    """Descriptor for one scheduled DR / Chaos experiment.

    New in P3 execution: ``provider_ref``, ``is_production_target``,
    ``has_rollback_path``, ``stop_conditions``, and ``kind`` are the
    per-experiment surface the four safety invariants read before the
    runner is invoked. Defaults are set so existing decision-only
    callers keep working — but ``DrScheduler.run`` refuses to enforce
    a run whose declaration does not satisfy every invariant.
    """

    experiment_id: str
    target_resource_ref: str
    target_resource_tags: frozenset[str] = field(default_factory=frozenset)
    scheduled_at: datetime | None = None
    provider_ref: str | None = None
    """ARM resource id (or CSP-neutral equivalent) of the experiment
    resource — Chaos Studio experiment or Site Recovery recovery plan.

    Required for ``ExecutionMode.ENFORCE``; ``None`` for shadow-only
    scheduler decisions.
    """

    is_production_target: bool = False
    """Isolation invariant: production is never a chaos target.

    A ``True`` value on ``ExecutionMode.ENFORCE`` short-circuits before
    the runner is invoked; overriding this MUST go through HIL, not
    through the automated executor.
    """

    has_rollback_path: bool = False
    """Rollback invariant: the experiment declares a tested rollback.

    A ``False`` value on ``ExecutionMode.ENFORCE`` short-circuits — a
    run without a rollback is by definition unsafe to auto-execute.
    """

    stop_conditions: tuple[str, ...] = ()
    """Stop-condition invariant: at least one abort trigger declared.

    Values are opaque identifiers understood by the runner (e.g.
    ``health-probe-failure``, ``error-rate>1pct``). An empty tuple on
    ``ExecutionMode.ENFORCE`` short-circuits.
    """


class ExecutionMode(StrEnum):
    """Whether a scheduler run mutates the substrate or just logs the decision.

    Shadow-mode runs judge-and-log only — the runner is NEVER invoked.
    Enforce-mode runs invoke the runner after all four safety
    invariants pass their preflight check.
    """

    SHADOW = "shadow"
    ENFORCE = "enforce"


class RunOutcome(StrEnum):
    """Terminal outcome of one :meth:`DrScheduler.run` call."""

    NOT_ALLOWED = "not_allowed"
    """The scheduler decision blocked the run (window/freeze/opt-out/cap)."""

    ISOLATION_VIOLATION = "isolation_violation"
    """The experiment targets a production resource; refused by policy."""

    MISSING_ROLLBACK_PATH = "missing_rollback_path"
    """The experiment did not declare a rollback contract."""

    MISSING_STOP_CONDITION = "missing_stop_condition"
    """The experiment did not declare at least one stop-condition."""

    MISSING_PROVIDER_REF = "missing_provider_ref"
    """The experiment has no ARM id / provider ref to hand to the runner."""

    RUNNER_NOT_CONFIGURED = "runner_not_configured"
    """``ExecutionMode.ENFORCE`` requested but no runner was injected."""

    SHADOW_LOGGED = "shadow_logged"
    """The decision passed every invariant but the caller asked for shadow."""

    EXECUTED = "executed"
    """The runner ran and reported success."""

    FAILED = "failed"
    """The runner raised or returned :class:`DrRunStatus.FAILED`."""

    ROLLED_BACK = "rolled_back"
    """The run failed or was stopped; rollback was invoked."""


@dataclass(frozen=True, slots=True)
class DrSchedulerConfig:
    """Scheduler policy knobs — every value is auditable config."""

    max_concurrent_experiments: int = 1
    """Cap on in-flight runs. Blast-radius limit on the whole tenant."""

    opt_out_tag: str = "chaos:opt-out"
    """Tag key/value that removes a resource from chaos scope."""


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    """Frozen record per experiment / moment pair."""

    experiment_id: str
    outcome: SchedulerOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DrRunResult:
    """Frozen record for one :meth:`DrScheduler.run` call.

    Carries the scheduler ``decision`` plus the execution outcome so a
    caller (P3 orchestrator) can audit both the "why" (window / cap /
    safety-invariant) and the "what happened" (runner start success /
    rollback / etc.) from a single record.

    ``handle`` is populated only when the runner was invoked. ``status``
    is the last observed :class:`DrRunStatus`; ``error`` carries a
    short-truncated failure reason and never a raw exception traceback
    (per the coding conventions on error messages).
    """

    experiment_id: str
    outcome: RunOutcome
    decision: SchedulerDecision
    handle: DrRunHandle | None = None
    status: DrRunStatus | None = None
    """The last observed :class:`DrRunStatus`, or ``None`` if the runner
    was never invoked."""

    error: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime | None = None


class DrScheduler:
    """Decision + safety-invariant preflight + optional runner invocation.

    ``decide`` remains pure: it returns a :class:`SchedulerDecision`
    with no I/O and no runner call. ``run`` is the P3 orchestration
    entry point — it evaluates the decision, enforces the four DR
    safety invariants (stop-condition, blast-radius/concurrency,
    rollback, isolation), and only then invokes the injected
    :class:`~aiopspilot.shared.providers.dr_experiment.DrExperimentRunner`.
    Shadow-mode runs never invoke the runner.
    """

    def __init__(
        self,
        *,
        windows: Iterable[MaintenanceWindow],
        freezes: Iterable[FreezePeriod] = (),
        config: DrSchedulerConfig | None = None,
        runner: DrExperimentRunner | None = None,
    ) -> None:
        cfg = config or DrSchedulerConfig()
        if cfg.max_concurrent_experiments < 1:
            raise ValueError("max_concurrent_experiments MUST be >= 1")
        self._windows = tuple(windows)
        self._freezes = tuple(freezes)
        self._config = cfg
        self._runner = runner

    def decide(
        self,
        *,
        experiment: DrExperiment,
        at: datetime | None = None,
        in_flight_experiments: int = 0,
    ) -> SchedulerDecision:
        """Return the scheduler outcome for ``experiment`` at time ``at``."""
        moment = at or datetime.now(tz=UTC)

        # 1. Freeze wins over window (an active freeze blocks any run).
        for freeze in self._freezes:
            if freeze.contains(moment):
                return SchedulerDecision(
                    experiment_id=experiment.experiment_id,
                    outcome=SchedulerOutcome.FROZEN,
                    reasons=(f"freeze:{freeze.name}",),
                    at=moment,
                )

        # 2. Window must be active.
        active = [w for w in self._windows if w.contains(moment)]
        if not active:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.OUTSIDE_WINDOW,
                reasons=("no_active_window",),
                at=moment,
            )

        # 3. Opt-out tag on the target resource → skip.
        if self._config.opt_out_tag in experiment.target_resource_tags:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.OPT_OUT,
                reasons=(f"opt_out_tag:{self._config.opt_out_tag}",),
                at=moment,
            )

        # 4. Concurrency cap.
        if in_flight_experiments >= self._config.max_concurrent_experiments:
            return SchedulerDecision(
                experiment_id=experiment.experiment_id,
                outcome=SchedulerOutcome.CONCURRENCY_CAP,
                reasons=(
                    f"in_flight={in_flight_experiments}>=cap="
                    f"{self._config.max_concurrent_experiments}",
                ),
                at=moment,
            )

        return SchedulerDecision(
            experiment_id=experiment.experiment_id,
            outcome=SchedulerOutcome.ALLOWED,
            reasons=(f"window:{active[0].name}",),
            at=moment,
        )

    async def run(
        self,
        *,
        experiment: DrExperiment,
        mode: ExecutionMode,
        at: datetime | None = None,
        in_flight_experiments: int = 0,
    ) -> DrRunResult:
        """Decide, enforce safety invariants, then dispatch to the runner.

        Order of operations (each step MUST hold before the next runs):

        1. :meth:`decide` — window / freeze / opt-out / concurrency-cap.
        2. **Isolation invariant** — refuse a production target.
        3. **Rollback invariant** — refuse an experiment without a
           declared rollback contract.
        4. **Stop-condition invariant** — refuse an experiment without
           at least one stop-condition.
        5. **Shadow-vs-enforce mode** — shadow logs only; enforce
           checks the runner is wired.
        6. **Runner start → check → (optional) rollback** — invoke the
           runner and, on any non-``SUCCEEDED`` terminal state or any
           exception during ``check``, invoke rollback exactly once.

        A shadow run never invokes the runner, matching the "shadow
        mode never mutates" property in the coding conventions.
        """
        moment = at or datetime.now(tz=UTC)
        decision = self.decide(
            experiment=experiment,
            at=moment,
            in_flight_experiments=in_flight_experiments,
        )
        if decision.outcome is not SchedulerOutcome.ALLOWED:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.NOT_ALLOWED,
                decision=decision,
                at=moment,
            )

        if experiment.is_production_target:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.ISOLATION_VIOLATION,
                decision=decision,
                at=moment,
                reasons=("isolation:target_is_production",),
            )

        if not experiment.has_rollback_path:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_ROLLBACK_PATH,
                decision=decision,
                at=moment,
                reasons=("rollback:not_declared",),
            )

        if not experiment.stop_conditions:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_STOP_CONDITION,
                decision=decision,
                at=moment,
                reasons=("stop_condition:not_declared",),
            )

        if mode is ExecutionMode.SHADOW:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.SHADOW_LOGGED,
                decision=decision,
                at=moment,
                reasons=("mode:shadow",),
            )

        # ENFORCE: everything below MAY mutate the substrate.
        if experiment.provider_ref is None:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.MISSING_PROVIDER_REF,
                decision=decision,
                at=moment,
                reasons=("provider_ref:required_for_enforce",),
            )

        if self._runner is None:
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.RUNNER_NOT_CONFIGURED,
                decision=decision,
                at=moment,
                reasons=("runner:not_injected",),
            )

        return await self._invoke_runner(experiment=experiment, decision=decision, at=moment)

    async def _invoke_runner(
        self,
        *,
        experiment: DrExperiment,
        decision: SchedulerDecision,
        at: datetime,
    ) -> DrRunResult:
        # Guarded by ``run`` — runner is not None at this point.
        runner = self._runner
        assert runner is not None  # noqa: S101 — invariant check for mypy

        try:
            handle = await runner.start(experiment)
        except Exception as exc:  # noqa: BLE001 — runner surface is untyped by Protocol
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.FAILED,
                decision=decision,
                at=at,
                error=_truncate_error(exc),
                reasons=("runner:start_failed",),
            )

        # A ``check`` failure is treated as a stop-condition trip: we
        # attempt a rollback and record the run as rolled back. Any
        # further failure of ``rollback`` itself is recorded but does
        # not mask the original error.
        try:
            status = await runner.check(handle)
        except Exception as exc:  # noqa: BLE001 — Protocol surface
            rollback_error = await _safe_rollback(runner, handle)
            reasons: tuple[str, ...] = ("runner:check_failed",)
            if rollback_error is not None:
                reasons = (*reasons, "rollback:error")
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.ROLLED_BACK,
                decision=decision,
                handle=handle,
                at=at,
                error=_truncate_error(exc),
                reasons=reasons,
            )

        if status in _ROLLBACK_STATUSES:
            rollback_error = await _safe_rollback(runner, handle)
            status_reasons: tuple[str, ...] = (f"runner:status={status.value}",)
            if rollback_error is not None:
                status_reasons = (*status_reasons, "rollback:error")
            return DrRunResult(
                experiment_id=experiment.experiment_id,
                outcome=RunOutcome.ROLLED_BACK,
                decision=decision,
                handle=handle,
                status=status,
                at=at,
                reasons=status_reasons,
            )

        return DrRunResult(
            experiment_id=experiment.experiment_id,
            outcome=RunOutcome.EXECUTED,
            decision=decision,
            handle=handle,
            status=status,
            at=at,
            reasons=(f"runner:status={status.value}",),
        )


# ---------------------------------------------------------------------------
# RPO / RTO measurement + reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrRunReport:
    """Measured outcome of one completed DR run."""

    experiment_id: str
    completed_at: datetime
    rpo_seconds: float
    """Actual data loss window (older = worse)."""

    rto_seconds: float
    """Wall-clock from failover trigger to verified restored service."""

    integrity_mismatches: int = 0
    smoke_pass: bool = True


_MEDIAN_SENTINEL: Final[float] = -1.0


@dataclass(frozen=True, slots=True)
class DrObjective:
    """Stated RPO/RTO objective for a run cohort."""

    max_rpo_seconds: float
    max_rto_seconds: float


@dataclass(frozen=True, slots=True)
class DrObjectiveReport:
    """Aggregate over a window of :class:`DrRunReport`s vs a stated objective.

    Emits median + p90 per phase-3 § RPO/RTO reporting. When the run
    count is zero, medians default to :data:`_MEDIAN_SENTINEL` — the
    caller renders that as "no data" rather than silently averaging.
    """

    objective: DrObjective
    run_count: int
    rpo_median_seconds: float
    rpo_p90_seconds: float
    rto_median_seconds: float
    rto_p90_seconds: float
    breach_count: int
    integrity_mismatches_total: int
    smoke_failures: int

    @property
    def rpo_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rpo_p90_seconds <= self.objective.max_rpo_seconds

    @property
    def rto_objective_met(self) -> bool:
        if self.run_count == 0:
            return False
        return self.rto_p90_seconds <= self.objective.max_rto_seconds


def summarize_runs(*, runs: Iterable[DrRunReport], objective: DrObjective) -> DrObjectiveReport:
    """Produce an :class:`DrObjectiveReport` from a run list.

    Empty run lists return sentinel medians so the caller can render
    "no data" rather than a false zero — phase-3 § RPO/RTO reporting.
    """
    runs_list = list(runs)
    if not runs_list:
        return DrObjectiveReport(
            objective=objective,
            run_count=0,
            rpo_median_seconds=_MEDIAN_SENTINEL,
            rpo_p90_seconds=_MEDIAN_SENTINEL,
            rto_median_seconds=_MEDIAN_SENTINEL,
            rto_p90_seconds=_MEDIAN_SENTINEL,
            breach_count=0,
            integrity_mismatches_total=0,
            smoke_failures=0,
        )

    rpos = sorted(r.rpo_seconds for r in runs_list)
    rtos = sorted(r.rto_seconds for r in runs_list)
    breach = sum(
        1
        for r in runs_list
        if r.rpo_seconds > objective.max_rpo_seconds or r.rto_seconds > objective.max_rto_seconds
    )

    return DrObjectiveReport(
        objective=objective,
        run_count=len(runs_list),
        rpo_median_seconds=median(rpos),
        rpo_p90_seconds=_percentile(rpos, 0.9),
        rto_median_seconds=median(rtos),
        rto_p90_seconds=_percentile(rtos, 0.9),
        breach_count=breach,
        integrity_mismatches_total=sum(r.integrity_mismatches for r in runs_list),
        smoke_failures=sum(1 for r in runs_list if not r.smoke_pass),
    )


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile for a small sample.

    Matches the phase-3 doc's ``median and p90`` convention; robust to
    very small run counts (a fresh cohort).
    """
    if not sorted_values:
        return _MEDIAN_SENTINEL
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(1, int(round(p * len(sorted_values))))
    rank = min(rank, len(sorted_values))
    return sorted_values[rank - 1]


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


_ROLLBACK_STATUSES: Final[frozenset[DrRunStatus]] = frozenset(
    {DrRunStatus.FAILED, DrRunStatus.STOPPED}
)
"""Statuses that trigger a rollback invocation.

``RUNNING`` returning from :meth:`DrExperimentRunner.check` is not a
rollback trigger — the caller is expected to poll again. The P3
scheduler treats the check as a one-shot query per :meth:`run` call.
"""


_ERROR_MESSAGE_CAP: Final[int] = 200


def _truncate_error(exc: BaseException) -> str:
    """Short, log-safe rendering of ``exc``.

    Never carries a raw traceback or a full vendor error body; a
    truncated ``str(exc)`` is enough for audit correlation and safe
    to persist per the coding-conventions on error strings.
    """
    text = str(exc).replace("\n", " ")
    if len(text) > _ERROR_MESSAGE_CAP:
        return text[:_ERROR_MESSAGE_CAP] + "…"
    return text


async def _safe_rollback(runner: DrExperimentRunner, handle: DrRunHandle) -> BaseException | None:
    """Invoke ``runner.rollback`` and swallow any exception.

    Rollback is best-effort by contract — the Protocol requires
    idempotency, but a substrate outage MAY still raise. We record the
    error on the run result so an operator can retry manually, but the
    original failure that triggered the rollback is preserved as the
    primary outcome.
    """
    try:
        await runner.rollback(handle)
    except Exception as exc:  # noqa: BLE001 — Protocol surface is untyped
        return exc
    return None


__all__ = [
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
    "RunOutcome",
    "SchedulerDecision",
    "SchedulerOutcome",
    "summarize_runs",
]
