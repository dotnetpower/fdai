"""DR / Chaos experiment runner Protocol.

Realizes the wire-level contract the P3 ``DrScheduler`` uses to actually
drive a chaos experiment or a Site Recovery test failover once the
scheduler's decision + safety-invariant preflight approve execution.
The Protocol is intentionally minimal - three async operations that
map cleanly onto both Azure Chaos Studio and Azure Site Recovery REST
surfaces, and onto an in-memory fake for unit tests.

Design boundaries
-----------------

- ``core/`` MAY reference this Protocol (it lives under
  ``fdai.shared.providers``) but MUST NOT import a concrete
  implementation. Bindings happen at the composition root; the Azure
  adapter under ``fdai.delivery.azure.dr_experiment`` and the
  in-memory fake under
  ``fdai.shared.providers.testing.dr_experiment`` never leak
  through ``core/``.
- Every operation is ``async`` because a real runner makes HTTP calls
  under a bearer token issued by
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`.
- The Protocol is state-free: the caller owns a :class:`DrRunHandle`
  and hands it back on ``check`` / ``rollback``. That keeps the runner
  reusable across concurrent experiments without a shared session.

Safety invariants
-----------------

The Protocol is only invoked *after* the four DR safety invariants
(stop-condition, blast-radius, rollback path, isolation) are enforced
by the caller. This module carries no policy - it is a delivery
seam. Any decision to run or not to run lives in
:class:`~fdai.core.verticals.resilience.DrScheduler`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.verticals.resilience import DrExperiment


class DrExperimentKind(StrEnum):
    """The two DR experiment surfaces this Protocol targets.

    Both are addressable via Azure Resource Manager REST; the concrete
    adapter dispatches on this value. Adding a new kind is an
    intentional, reviewable change (Protocol expansion) - never a
    wildcard on ``experiment.provider_ref``.
    """

    CHAOS = "chaos"
    """Azure Chaos Studio experiment - ``POST .../experiments/{name}/start``."""

    SITE_RECOVERY_TEST_FAILOVER = "site_recovery_test_failover"
    """Azure Site Recovery test failover - ``POST .../plannedFailover``."""


class DrRunStatus(StrEnum):
    """Terminal-or-intermediate state of one in-flight run.

    A runner's ``check`` returns exactly one of these; the scheduler
    treats every non-``SUCCEEDED`` terminal state as a rollback trigger.
    """

    RUNNING = "running"
    """The run has been accepted and is executing."""

    SUCCEEDED = "succeeded"
    """The run finished cleanly; no rollback needed."""

    FAILED = "failed"
    """The run finished with an error; the caller MUST invoke rollback."""

    STOPPED = "stopped"
    """A stop-condition fired mid-flight; the caller MUST invoke rollback."""


@dataclass(frozen=True, slots=True)
class DrRunHandle:
    """Opaque reference to one in-flight DR run.

    Frozen so the caller cannot mutate the pointer to another run - the
    handle carries just enough identity for a subsequent
    ``check`` / ``rollback`` round trip. ``provider_ref`` is the ARM
    resource id (or equivalent CSP path) of the experiment resource;
    ``run_id`` is the substrate-issued execution id (Chaos Studio
    ``executionDetails.id``) or the LRO ticket id from Site Recovery.
    """

    experiment_id: str
    kind: DrExperimentKind
    provider_ref: str
    run_id: str
    started_at: datetime
    status_url: str | None = None
    """Absolute URL to poll for run status; ``None`` for synchronous fakes.

    Real Azure endpoints return an ``Azure-AsyncOperation`` or
    ``Location`` header on 202 - the adapter stores that URL here so
    ``check`` can poll without recomputing it from the ARM id.
    """


class DrRunnerError(RuntimeError):
    """Raised by a :class:`DrExperimentRunner` on any unrecoverable failure.

    The message is safe to log - implementations MUST NOT embed raw
    tokens, subscription ids, or vendor error bodies larger than a short
    truncated snippet.
    """

    def __init__(
        self,
        message: str,
        *,
        experiment_id: str,
        kind: DrExperimentKind,
        status_code: int | None = None,
    ) -> None:
        code = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{message}{code} [experiment_id={experiment_id}, kind={kind.value}]")
        self.message = message
        self.experiment_id = experiment_id
        self.kind = kind
        self.status_code = status_code


@runtime_checkable
class DrExperimentRunner(Protocol):
    """Start / check / rollback a DR or Chaos experiment.

    The three operations map onto both target substrates:

    +---------------+--------------------------+-------------------------------+
    | Op            | Chaos Studio             | Site Recovery                 |
    +===============+==========================+===============================+
    | ``start``     | ``POST .../start``       | ``POST .../plannedFailover``  |
    | ``check``     | ``GET  .../executions``  | ``GET  {status_url}``         |
    | ``rollback``  | ``POST .../cancel``      | ``POST .../plannedFailoverCleanup`` |
    +---------------+--------------------------+-------------------------------+

    ``rollback`` MUST be idempotent - the scheduler calls it on any
    non-``SUCCEEDED`` terminal status and on any exception raised
    during ``check``; a rollback on an already-rolled-back run MUST
    NOT raise.
    """

    async def start(self, experiment: DrExperiment) -> DrRunHandle:
        """Kick off a run and return a handle for subsequent ``check`` / ``rollback``.

        Raises :class:`DrRunnerError` on immediate failure (invalid ARM
        id, missing auth, 4xx/5xx) so the caller can audit the failure
        without touching the runner state.
        """
        ...

    async def check(self, handle: DrRunHandle) -> DrRunStatus:
        """Return the current status of the run pointed at by ``handle``.

        Raises :class:`DrRunnerError` on transport / auth failure.
        A polling loop belongs to the caller, not the runner - the
        Protocol stays a one-shot query so the scheduler owns the
        stop-condition timing.
        """
        ...

    async def rollback(self, handle: DrRunHandle) -> None:
        """Revert or cancel the run.

        Must be idempotent (``rollback`` on a completed / cancelled /
        never-started run MUST NOT raise). Errors that indicate the
        runtime substrate is unreachable MAY raise
        :class:`DrRunnerError` - the caller escalates to HIL.
        """
        ...


__all__ = [
    "DrExperimentKind",
    "DrExperimentRunner",
    "DrRunHandle",
    "DrRunStatus",
    "DrRunnerError",
]
