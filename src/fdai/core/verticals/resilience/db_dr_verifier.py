"""Deep DB-DR verifier - restore → integrity → smoke orchestrator.

Realizes the phase-3 Deep DB-DR contract in
[`docs/roadmap/phases/phase-3-integrated-loop.md § Deep DB-DR`]:

    1. Restore a snapshot / PITR into an **isolated environment**.
    2. Verify integrity deterministically - row counts, checksums, FK
       consistency. **Any** mismatch fails the run.
    3. Run app-level smoke tests - representative read + write ops.

The orchestrator is pure - every side effect (substrate mutation,
audit persistence) sits behind an injected Protocol seam. This
module contains no HTTP, no SDK, and no I/O of its own; it MUST be
importable from `core/` without pulling any CSP dependency.

Safety invariants
-----------------

- **Fail on ANY integrity mismatch** - the checker returns an
  exhaustive :class:`IntegrityReport`; the verifier records every
  mismatch, does not average, and returns
  :attr:`DbDrOutcome.INTEGRITY_FAILED` if the count is nonzero.
- **Fail-closed on exceptions** - a raised exception from any phase
  is an abort, never a "clean" verdict. The verifier tears the
  restored environment down and returns
  :attr:`DbDrOutcome.ABORTED`.
- **Teardown always runs after a successful restore** - the restored
  environment is torn down in a ``finally`` clause so a partial pass
  never leaks an isolated resource group. A teardown error is
  recorded on the verdict + audit log but does not mask the primary
  outcome.
- **Every terminal path writes an audit entry** - start, restore
  failure, integrity failure, smoke failure, abort, and success each
  emit exactly one append-only :class:`StateStore` entry with the
  experiment id, outcome, and structured evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.shared.providers.db_dr import (
    DbDrEvidence,
    DbRestoreAdapter,
    DbRestoreConfig,
    DbRestoreHandle,
    IntegrityChecker,
    IntegrityReport,
    SmokeReport,
    SmokeRunner,
)
from fdai.shared.providers.state_store import StateStore

_AUDIT_EVENT_KIND = "db_dr_verifier"
_ERROR_MESSAGE_CAP = 200


class DbDrOutcome(StrEnum):
    """Terminal verdict of one :meth:`DbDrVerifier.run` call."""

    PASSED = "passed"
    """Restore, integrity, and smoke all succeeded."""

    RESTORE_FAILED = "restore_failed"
    """The restore adapter raised or refused isolation."""

    INTEGRITY_FAILED = "integrity_failed"
    """The integrity checker reported at least one mismatch."""

    SMOKE_FAILED = "smoke_failed"
    """The smoke runner returned a report whose ``passed`` is False."""

    ABORTED = "aborted"
    """Integrity or smoke raised an exception; the run is undecided."""


@dataclass(frozen=True, slots=True)
class DbDrVerdict:
    """Frozen record for one :meth:`DbDrVerifier.run` call.

    Carries the outcome plus every structured piece of evidence the
    audit log persists - the report objects, a truncated error string
    if applicable, and the wall-clock envelope. Teardown outcome is
    NOT surfaced on the verdict directly - it lands as a separate
    audit entry (``teardown_succeeded`` / ``teardown_failed``) so the
    primary outcome stays a single-source-of-truth value.
    """

    experiment_id: str
    outcome: DbDrOutcome
    handle: DbRestoreHandle | None = None
    integrity: IntegrityReport | None = None
    smoke: SmokeReport | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_pass(self) -> bool:
        """Convenience - the DR test passed iff outcome is PASSED."""
        return self.outcome is DbDrOutcome.PASSED


class DbDrVerifier:
    """Restore → integrity → smoke orchestrator.

    Every phase is an injected Protocol so the orchestrator stays
    CSP-neutral and unit-testable without any transport / substrate
    round trip.
    """

    def __init__(
        self,
        *,
        restore: DbRestoreAdapter,
        integrity: IntegrityChecker,
        smoke: SmokeRunner,
        audit: StateStore,
    ) -> None:
        self._restore: DbRestoreAdapter = restore
        self._integrity: IntegrityChecker = integrity
        self._smoke: SmokeRunner = smoke
        self._audit: StateStore = audit

    async def run(self, config: DbRestoreConfig) -> DbDrVerdict:
        """Execute the three-phase Deep DB-DR verifier.

        Order of operations:

        1. Audit ``kind=start``.
        2. :meth:`DbRestoreAdapter.restore` - on failure, audit
           ``kind=restore_failed`` and return :attr:`RESTORE_FAILED`.
        3. :meth:`IntegrityChecker.check` - on ANY mismatch, audit
           ``kind=integrity_failed`` and return
           :attr:`INTEGRITY_FAILED`; on exception, audit
           ``kind=aborted`` and return :attr:`ABORTED`.
        4. :meth:`SmokeRunner.run` - on non-pass, audit
           ``kind=smoke_failed`` and return :attr:`SMOKE_FAILED`;
           on exception, audit ``kind=aborted`` and return
           :attr:`ABORTED`.
        5. Audit ``kind=passed`` and return :attr:`PASSED`.

        In every case except ``RESTORE_FAILED`` (no handle to tear
        down) the restored environment is torn down before returning;
        a teardown error is audited as a separate event but does not
        change the primary outcome.
        """
        started_at = datetime.now(tz=UTC)
        await self._audit_event(
            experiment_id=config.experiment_id,
            kind="start",
            payload={
                "source_ref": config.source_ref,
                "target_resource_group": config.target_resource_group,
                "target_server_name": config.target_server_name,
                "point_in_time_utc": _iso_or_none(config.point_in_time_utc),
                "at": started_at.isoformat(),
            },
        )

        # ---------- Phase 1: restore -------------------------------------------------
        try:
            handle = await self._restore.restore(config)
        except Exception as exc:  # noqa: BLE001 - Protocol surface is untyped
            error = _truncate_error(exc)
            completed_at = datetime.now(tz=UTC)
            await self._audit_event(
                experiment_id=config.experiment_id,
                kind="restore_failed",
                payload={"error": error, "at": completed_at.isoformat()},
            )
            return DbDrVerdict(
                experiment_id=config.experiment_id,
                outcome=DbDrOutcome.RESTORE_FAILED,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )

        # From here on, handle is populated: teardown MUST run in the
        # finally block so a partial pass never leaks the isolated
        # environment.
        try:
            return await self._verify_and_smoke(
                config=config,
                handle=handle,
                started_at=started_at,
            )
        finally:
            # Best-effort teardown; recorded on the verdict via audit
            # if it fails. The primary outcome is already frozen in
            # the returned DbDrVerdict at this point.
            await self._safe_teardown(handle=handle)

    # ------------------------------------------------------------------
    # Phase 2 + 3 (internals)
    # ------------------------------------------------------------------

    async def _verify_and_smoke(
        self,
        *,
        config: DbRestoreConfig,
        handle: DbRestoreHandle,
        started_at: datetime,
    ) -> DbDrVerdict:
        # ---------- Phase 2: integrity check ---------------------------
        try:
            integrity = await self._integrity.check(handle)
        except Exception as exc:  # noqa: BLE001 - Protocol surface is untyped
            error = _truncate_error(exc)
            completed_at = datetime.now(tz=UTC)
            await self._audit_event(
                experiment_id=config.experiment_id,
                kind="aborted",
                payload={
                    "phase": "integrity",
                    "error": error,
                    "at": completed_at.isoformat(),
                },
            )
            return DbDrVerdict(
                experiment_id=config.experiment_id,
                outcome=DbDrOutcome.ABORTED,
                handle=handle,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )

        if not integrity.is_clean:
            # Record every mismatch - never average away. The audit
            # payload carries structured evidence so an operator can
            # reproduce the failure from the log alone.
            completed_at = datetime.now(tz=UTC)
            await self._audit_event(
                experiment_id=config.experiment_id,
                kind="integrity_failed",
                payload={
                    "mismatch_count": integrity.mismatch_count,
                    "mismatches": [
                        {
                            "kind": m.kind.value,
                            "table": m.table,
                            "detail": m.detail,
                        }
                        for m in integrity.mismatches
                    ],
                    "at": completed_at.isoformat(),
                },
            )
            return DbDrVerdict(
                experiment_id=config.experiment_id,
                outcome=DbDrOutcome.INTEGRITY_FAILED,
                handle=handle,
                integrity=integrity,
                started_at=started_at,
                completed_at=completed_at,
            )

        # ---------- Phase 3: smoke tests -------------------------------
        try:
            smoke = await self._smoke.run(handle)
        except Exception as exc:  # noqa: BLE001 - Protocol surface is untyped
            error = _truncate_error(exc)
            completed_at = datetime.now(tz=UTC)
            await self._audit_event(
                experiment_id=config.experiment_id,
                kind="aborted",
                payload={
                    "phase": "smoke",
                    "error": error,
                    "at": completed_at.isoformat(),
                },
            )
            return DbDrVerdict(
                experiment_id=config.experiment_id,
                outcome=DbDrOutcome.ABORTED,
                handle=handle,
                integrity=integrity,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )

        if not smoke.passed:
            completed_at = datetime.now(tz=UTC)
            await self._audit_event(
                experiment_id=config.experiment_id,
                kind="smoke_failed",
                payload={
                    "failed_check_count": len(smoke.failures),
                    "failures": [{"name": c.name, "detail": c.detail} for c in smoke.failures],
                    "checks_total": len(smoke.checks),
                    "at": completed_at.isoformat(),
                },
            )
            return DbDrVerdict(
                experiment_id=config.experiment_id,
                outcome=DbDrOutcome.SMOKE_FAILED,
                handle=handle,
                integrity=integrity,
                smoke=smoke,
                started_at=started_at,
                completed_at=completed_at,
            )

        # ---------- Success -------------------------------------------
        completed_at = datetime.now(tz=UTC)
        evidence = DbDrEvidence(
            integrity_row_count_tables=len(integrity.table_row_counts),
            integrity_checksum_tables=len(integrity.checksums),
            integrity_mismatches=(),
            smoke_checks_total=len(smoke.checks),
            smoke_failures=(),
        )
        await self._audit_event(
            experiment_id=config.experiment_id,
            kind="passed",
            payload={
                "evidence": {
                    "integrity_row_count_tables": evidence.integrity_row_count_tables,
                    "integrity_checksum_tables": evidence.integrity_checksum_tables,
                    "smoke_checks_total": evidence.smoke_checks_total,
                },
                "at": completed_at.isoformat(),
            },
        )
        return DbDrVerdict(
            experiment_id=config.experiment_id,
            outcome=DbDrOutcome.PASSED,
            handle=handle,
            integrity=integrity,
            smoke=smoke,
            started_at=started_at,
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Teardown + audit helpers
    # ------------------------------------------------------------------

    async def _safe_teardown(self, *, handle: DbRestoreHandle) -> None:
        """Invoke the restore adapter's teardown; swallow + audit errors.

        A teardown failure is recorded to the audit log as a separate
        entry so the reviewer can see it, but it does not overwrite
        the primary outcome (which was already returned before this
        finally clause runs).
        """
        try:
            await self._restore.teardown(handle)
        except Exception as exc:  # noqa: BLE001 - Protocol surface is untyped
            error = _truncate_error(exc)
            await self._audit_event(
                experiment_id=handle.experiment_id,
                kind="teardown_failed",
                payload={
                    "error": error,
                    "target_ref": handle.target_ref,
                    "at": datetime.now(tz=UTC).isoformat(),
                },
            )
            return
        await self._audit_event(
            experiment_id=handle.experiment_id,
            kind="teardown_succeeded",
            payload={
                "target_ref": handle.target_ref,
                "at": datetime.now(tz=UTC).isoformat(),
            },
        )

    async def _audit_event(
        self,
        *,
        experiment_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Append one canonical audit record.

        The audit envelope is stable across every terminal path so
        downstream tooling (KPI dashboards, alerting) can filter on
        ``event_kind == 'db_dr_verifier'`` and read the ``kind`` field
        to distinguish phases.
        """
        entry = {
            "event_kind": _AUDIT_EVENT_KIND,
            "experiment_id": experiment_id,
            "kind": kind,
            "payload": dict(payload),
        }
        await self._audit.append_audit_entry(entry)


def _iso_or_none(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def _truncate_error(exc: BaseException) -> str:
    """Short, log-safe rendering of ``exc``.

    Never carries a raw traceback or a full vendor error body; a
    truncated ``str(exc)`` is enough for audit correlation and safe
    to persist per the coding-conventions rule on error strings.
    """
    text = str(exc).replace("\n", " ")
    if len(text) > _ERROR_MESSAGE_CAP:
        return text[:_ERROR_MESSAGE_CAP] + "..."
    return text


__all__ = [
    "DbDrOutcome",
    "DbDrVerdict",
    "DbDrVerifier",
]
