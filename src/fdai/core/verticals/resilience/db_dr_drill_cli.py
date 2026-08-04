"""Deep DB-DR drill CLI entry point.

Container Apps Jobs (``infra/modules/compute/container-apps/dr_drill_job.tf``)
launch this module on the schedule documented in
[`docs/runbooks/db-dr-drill.md`](../../../../docs/runbooks/db-dr-drill.md).
The CLI composes a
:class:`~fdai.core.verticals.resilience.db_dr_verifier.DbDrVerifier` with
the shipped Azure adapter and runs one restore -> integrity -> smoke ->
teardown cycle.

Env-var contract
----------------

- ``FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID`` (required) - ARM id of
  the source PostgreSQL Flexible Server whose PITR checkpoint the
  drill restores. Never the drill target - restoring into a fresh
  isolated RG is the isolation invariant.
- ``FDAI_DR_DRILL_TARGET_LOCATION`` (required) - Azure region
  the drill target lands in (e.g. ``koreacentral``).
- ``FDAI_DR_DRILL_TARGET_RG_PREFIX`` (default ``rg-fdai-dr-drill``)
  - prefix for the isolated resource group name; the CLI appends a
  UTC timestamp so parallel drills never collide.
- ``FDAI_DR_DRILL_TARGET_SERVER_PREFIX`` (default ``psql-drill``)
  - Postgres server name prefix; combined with a short timestamp to
  stay within the 63-char Azure limit.
- ``FDAI_DR_DRILL_PITR_OFFSET_MINUTES`` (default ``30``) - how
  far back from ``now()`` the restore point sits. 30 min gives the
  PITR window slack; a fork tunes if the source retention differs.
- ``FDAI_DR_DRILL_DRY_RUN`` (default ``0``) - when ``1``, the
  CLI logs the composed :class:`DbRestoreConfig` and exits ``0``
  without touching Azure. Used by CI + the smoke test that verifies
  wire-up without a live cost.

Exit codes
----------

- ``0`` - drill passed. Restore + integrity + smoke all green.
- ``2`` - invalid / missing env config (fail-fast per coding-conventions).
- ``3`` - drill did not pass (any non-PASSED outcome). A regression
  demotion or paging follows on the audit trail, not on this exit
  code - but a non-zero exit tells the scheduler the drill did not
  clear its exit gate.
- ``4`` - unexpected runtime exception (adapter crashed outside the
  verifier's fail-close path).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fdai.core.verticals.resilience.db_dr_verifier import DbDrVerdict
from fdai.shared.providers.db_dr import DbRestoreConfig

_LOGGER = logging.getLogger("fdai.core.verticals.resilience.db_dr_drill_cli")


_ENV_SOURCE = "FDAI_DR_DRILL_SOURCE_SERVER_ARM_ID"
_ENV_LOCATION = "FDAI_DR_DRILL_TARGET_LOCATION"
_ENV_RG_PREFIX = "FDAI_DR_DRILL_TARGET_RG_PREFIX"
_ENV_SERVER_PREFIX = "FDAI_DR_DRILL_TARGET_SERVER_PREFIX"
_ENV_PITR_OFFSET = "FDAI_DR_DRILL_PITR_OFFSET_MINUTES"
_ENV_DRY_RUN = "FDAI_DR_DRILL_DRY_RUN"

_DEFAULT_RG_PREFIX = "rg-fdai-dr-drill"
_DEFAULT_SERVER_PREFIX = "psql-drill"
_DEFAULT_OFFSET_MINUTES = 30

DbDrDrillRunner = Callable[[DbRestoreConfig], Awaitable[DbDrVerdict]]


def _read_required(env_name: str) -> str | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        _LOGGER.error("db_dr_drill_missing_env", extra={"env": env_name})
        return None
    return raw


def _read_int(env_name: str, default: int) -> int | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        _LOGGER.error(
            "db_dr_drill_invalid_int_env",
            extra={"env": env_name, "value": raw},
        )
        return None
    if parsed <= 0:
        _LOGGER.error(
            "db_dr_drill_non_positive_env",
            extra={"env": env_name, "value": raw},
        )
        return None
    return parsed


def _timestamp_slug(moment: datetime) -> str:
    """Return the ``MMDDHHMM`` slug used in drill resource names."""
    return moment.strftime("%m%d%H%M")


def _rg_timestamp_slug(moment: datetime) -> str:
    """Return the ``YYYYMMDD-HHMM`` slug used in the drill RG name."""
    return moment.strftime("%Y%m%d-%H%M")


def _build_config(now: datetime) -> DbRestoreConfig | None:
    """Compose a :class:`DbRestoreConfig` from env; ``None`` on error."""
    source = _read_required(_ENV_SOURCE)
    if source is None:
        return None
    location = _read_required(_ENV_LOCATION)
    if location is None:
        return None
    rg_prefix = os.environ.get(_ENV_RG_PREFIX, "").strip() or _DEFAULT_RG_PREFIX
    server_prefix = os.environ.get(_ENV_SERVER_PREFIX, "").strip() or _DEFAULT_SERVER_PREFIX
    offset_minutes = _read_int(_ENV_PITR_OFFSET, _DEFAULT_OFFSET_MINUTES)
    if offset_minutes is None:
        return None

    ts_short = _timestamp_slug(now)
    ts_rg = _rg_timestamp_slug(now)
    target_rg = f"{rg_prefix}-{ts_rg}"
    target_server = f"{server_prefix}-{ts_short}"
    if len(target_server) > 63:
        _LOGGER.error(
            "db_dr_drill_target_server_name_too_long",
            extra={"target_server": target_server, "length": len(target_server)},
        )
        return None

    return DbRestoreConfig(
        experiment_id=f"db-dr-drill-{ts_rg}",
        source_ref=source,
        target_server_name=target_server,
        target_resource_group=target_rg,
        target_location=location,
        point_in_time_utc=now - timedelta(minutes=offset_minutes),
    )


async def _amain(*, run_drill: DbDrDrillRunner | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("FDAI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    now = datetime.now(tz=UTC)
    config = _build_config(now)
    if config is None:
        return 2

    dry_run = os.environ.get(_ENV_DRY_RUN, "").strip() in {"1", "true", "yes"}
    if dry_run:
        _LOGGER.info(
            "db_dr_drill_dry_run",
            extra={
                "experiment_id": config.experiment_id,
                "source_ref": config.source_ref,
                "target_server_name": config.target_server_name,
                "target_resource_group": config.target_resource_group,
                "target_location": config.target_location,
                "point_in_time_utc": (
                    config.point_in_time_utc.isoformat()
                    if config.point_in_time_utc is not None
                    else None
                ),
            },
        )
        return 0

    if run_drill is None:
        _LOGGER.info(
            "db_dr_drill_live_composition_required",
            extra={
                "experiment_id": config.experiment_id,
                "hint": (
                    "Bind DbRestoreAdapter / IntegrityChecker / SmokeRunner at the "
                    "composition root and pass DbDrVerifier.run to main."
                ),
            },
        )
        return 2

    verdict = await run_drill(config)
    return _verdict_to_exit_code(verdict)


def _verdict_to_exit_code(verdict: DbDrVerdict) -> int:
    """Convert a verdict to a shell exit code."""
    if verdict.is_pass:
        return 0
    return 3


def main(run_drill: DbDrDrillRunner | None = None) -> int:
    try:
        return asyncio.run(_amain(run_drill=run_drill))
    except Exception:
        _LOGGER.exception("db_dr_drill_unexpected_error")
        return 4


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["DbDrDrillRunner", "main"]
