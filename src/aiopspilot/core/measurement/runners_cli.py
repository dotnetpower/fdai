"""Phase-4 measurement runners CLI entry point.

Container Apps Jobs (``infra/modules/measurement-runners/``) launch this
module as their ``ExecStart`` — see the ``ExecutionStartCommand`` in the
Terraform module. The job's ``AIOPSPILOT_MEASUREMENT_MODE`` env var
picks which runner executes; every other seam is bound by the standard
composition root so the CLI never reaches an adapter directly.

Usage
-----

.. code-block:: shell

    AIOPSPILOT_MEASUREMENT_MODE=baseline python -m aiopspilot.core.measurement.runners_cli
    AIOPSPILOT_MEASUREMENT_MODE=growth   python -m aiopspilot.core.measurement.runners_cli

Exit codes
----------

- ``0`` — run completed (either the runner reported a clean pass OR a
  regression was detected and audited; both are "operational success").
- ``2`` — invalid ``AIOPSPILOT_MEASUREMENT_MODE`` (fail-fast per
  ``coding-conventions.instructions.md``).
- ``3`` — the runner raised an unexpected exception; the audit entry has
  already been written by the runner itself.

Contract with the Terraform Job
-------------------------------

The Container Apps Job runs the CLI **once per scheduled fire** (a
single replica, ``replica_completion_count=1``). A regression detection
does NOT fail the job — the outcome is a state transition (demote), not
a job error. Only a genuine runtime error causes exit ``3`` and paging.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from enum import StrEnum

_LOGGER = logging.getLogger("aiopspilot.core.measurement.runners_cli")

_ENV_MODE = "AIOPSPILOT_MEASUREMENT_MODE"


class MeasurementMode(StrEnum):
    BASELINE = "baseline"
    GROWTH = "growth"


def _resolve_mode() -> MeasurementMode | None:
    raw = os.environ.get(_ENV_MODE, "").strip().lower()
    if raw not in {m.value for m in MeasurementMode}:
        return None
    return MeasurementMode(raw)


async def _run_baseline() -> int:
    """Placeholder baseline runner entry.

    The full :class:`~aiopspilot.core.measurement.runners.AutomatedBaselineRunner`
    requires a live scenario replayer + regression detector + promotion
    registry. Those seams are bound in a fork's composition root; the
    upstream CLI logs a shadow-only summary and exits ``0`` so the
    Terraform Job can prove wire-up without prescribing a fork's
    replayer.

    A fork MAY subclass this CLI by importing
    :mod:`aiopspilot.composition`, binding the seams, and awaiting
    :meth:`AutomatedBaselineRunner.run`.
    """
    _LOGGER.info(
        "measurement_runner_baseline_start",
        extra={"mode": MeasurementMode.BASELINE.value},
    )
    # Nothing to do upstream: a fork overrides this entry point to
    # bind the concrete replayer + registry + audit store. The upstream
    # image ships the seam surface only — running against it should
    # succeed as a health probe.
    _LOGGER.info("measurement_runner_baseline_complete")
    return 0


async def _run_growth() -> int:
    """Placeholder pattern-growth intake entry.

    Same rationale as :func:`_run_baseline`: the full
    :class:`~aiopspilot.core.measurement.runners.PatternGrowthIntakeRunner`
    needs a live outcome source + pattern builder + T1 pattern library
    writer, which a fork wires in its composition root. Upstream logs
    and exits ``0``.
    """
    _LOGGER.info(
        "measurement_runner_growth_start",
        extra={"mode": MeasurementMode.GROWTH.value},
    )
    _LOGGER.info("measurement_runner_growth_complete")
    return 0


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("AIOPSPILOT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _amain() -> int:
    _configure_logging()
    mode = _resolve_mode()
    if mode is None:
        _LOGGER.error(
            "invalid_measurement_mode",
            extra={_ENV_MODE: os.environ.get(_ENV_MODE, "<unset>")},
        )
        return 2
    try:
        if mode is MeasurementMode.BASELINE:
            return await _run_baseline()
        return await _run_growth()
    except Exception:
        _LOGGER.exception("measurement_runner_unexpected_error", extra={"mode": mode.value})
        return 3


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
