"""Deep DB-DR verifier — end-to-end orchestrator tests.

Covers the phase-3 Deep DB-DR contract in
[`docs/roadmap/phases/phase-3-integrated-loop.md § Deep DB-DR`]:

- **Happy path** — restore, integrity, and smoke all succeed; the
  restored environment is torn down; every audit entry lands.
- **ANY integrity mismatch fails the run** — the verifier does not
  average; a single mismatch flips the outcome to
  ``INTEGRITY_FAILED`` and smoke is never invoked.
- **Smoke failure fails the run** — an empty check list or any
  failing check yields ``SMOKE_FAILED``.
- **Rollback-on-abort** — a raised exception from any phase after
  restore aborts the run AND tears the restored environment down;
  a raised exception on restore leaves no handle to tear down.
- **Every terminal path writes an audit entry** — start, one
  terminal marker (passed / restore_failed / integrity_failed /
  smoke_failed / aborted), and (except on restore_failed) exactly
  one teardown marker.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import pytest

from aiopspilot.core.verticals.db_dr_verifier import (
    DbDrOutcome,
    DbDrVerifier,
)
from aiopspilot.shared.providers.db_dr import (
    DbDrError,
    DbRestoreConfig,
    IntegrityMismatch,
    IntegrityMismatchKind,
    IntegrityReport,
    SmokeCheck,
    SmokeReport,
)
from aiopspilot.shared.providers.testing.db_dr import (
    FakeDbRestoreAdapter,
    FakeIntegrityChecker,
    FakeSmokeRunner,
    make_test_config,
)
from aiopspilot.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _clean_integrity() -> IntegrityReport:
    return IntegrityReport(
        table_row_counts={"orders": 100, "users": 50},
        checksums={"orders": "sha256:aa", "users": "sha256:bb"},
        mismatches=(),
    )


def _mismatched_integrity() -> IntegrityReport:
    return IntegrityReport(
        table_row_counts={"orders": 99, "users": 50},
        checksums={"orders": "sha256:aa", "users": "sha256:xx"},
        mismatches=(
            IntegrityMismatch(
                kind=IntegrityMismatchKind.ROW_COUNT,
                table="orders",
                detail="expected 100, got 99",
            ),
            IntegrityMismatch(
                kind=IntegrityMismatchKind.CHECKSUM,
                table="users",
                detail="sha256 diverged",
            ),
        ),
    )


def _passing_smoke() -> SmokeReport:
    return SmokeReport(
        checks=(
            SmokeCheck(name="read-recent-orders", passed=True),
            SmokeCheck(name="insert-then-select", passed=True),
        )
    )


def _failing_smoke() -> SmokeReport:
    return SmokeReport(
        checks=(
            SmokeCheck(name="read-recent-orders", passed=True),
            SmokeCheck(
                name="insert-then-select",
                passed=False,
                detail="write blocked by RO replica",
            ),
        )
    )


def _make_verifier(
    *,
    restore: FakeDbRestoreAdapter | None = None,
    integrity: FakeIntegrityChecker | None = None,
    smoke: FakeSmokeRunner | None = None,
    audit: InMemoryStateStore | None = None,
) -> tuple[
    DbDrVerifier, InMemoryStateStore, FakeDbRestoreAdapter, FakeIntegrityChecker, FakeSmokeRunner
]:
    restore = restore or FakeDbRestoreAdapter()
    integrity = integrity or FakeIntegrityChecker(report_sequence=(_clean_integrity(),))
    smoke = smoke or FakeSmokeRunner(report_sequence=(_passing_smoke(),))
    audit = audit or InMemoryStateStore()
    verifier = DbDrVerifier(
        restore=restore,
        integrity=integrity,
        smoke=smoke,
        audit=audit,
    )
    return verifier, audit, restore, integrity, smoke


def _audit_kinds(store: InMemoryStateStore) -> list[str]:
    kinds: list[str] = []
    for record in store.audit_entries:
        entry = record["entry"]
        assert entry["event_kind"] == "db_dr_verifier"
        kinds.append(entry["kind"])
    return kinds


def _find_audit_payload(store: InMemoryStateStore, kind: str) -> dict[str, Any]:
    for record in store.audit_entries:
        entry = record["entry"]
        if entry["kind"] == kind:
            return dict(entry["payload"])
    raise AssertionError(f"no audit entry with kind {kind!r} in {_audit_kinds(store)}")


def _assert_contains_in_order(actual: Iterable[str], expected: list[str]) -> None:
    """Assert that ``actual`` contains ``expected`` in the given order.

    Extra entries between the expected markers are allowed — the audit
    log MAY interleave phase markers, but the terminal marker MUST
    appear after the start marker, etc.
    """
    remaining = list(expected)
    for k in actual:
        if remaining and k == remaining[0]:
            remaining.pop(0)
    assert remaining == [], (
        f"expected {expected} as an ordered subsequence, but only reached "
        f"{expected[: len(expected) - len(remaining)]} in {list(actual)}"
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_passes_and_tears_down() -> None:
    verifier, audit, restore, integrity, smoke = _make_verifier()
    config = make_test_config(experiment_id="exp-happy")

    verdict = await verifier.run(config)

    assert verdict.outcome is DbDrOutcome.PASSED
    assert verdict.is_pass is True
    assert verdict.handle is not None
    assert verdict.integrity is not None and verdict.integrity.is_clean
    assert verdict.smoke is not None and verdict.smoke.passed
    assert verdict.error is None

    # All three phases were invoked exactly once.
    assert len(restore.restored) == 1
    assert len(integrity.checked) == 1
    assert len(smoke.smoked) == 1

    # Teardown happened exactly once with the same handle.
    assert len(restore.torn_down) == 1
    assert restore.torn_down[0].experiment_id == "exp-happy"

    # Audit entries: start → passed → teardown_succeeded (order).
    _assert_contains_in_order(
        _audit_kinds(audit),
        ["start", "passed", "teardown_succeeded"],
    )
    passed_payload = _find_audit_payload(audit, "passed")
    assert passed_payload["evidence"]["smoke_checks_total"] == 2
    assert passed_payload["evidence"]["integrity_row_count_tables"] == 2


async def test_start_audit_records_config_details() -> None:
    verifier, audit, *_ = _make_verifier()
    config = make_test_config(
        experiment_id="exp-audit",
        target_server_name="restored-1",
        target_resource_group="rg-restored-1",
    )
    await verifier.run(config)

    start = _find_audit_payload(audit, "start")
    assert start["target_server_name"] == "restored-1"
    assert start["target_resource_group"] == "rg-restored-1"
    assert start["source_ref"].startswith("/subscriptions/")
    assert start["point_in_time_utc"] is None


async def test_audit_chain_is_intact_across_run() -> None:
    verifier, audit, *_ = _make_verifier()
    await verifier.run(make_test_config(experiment_id="exp-chain"))
    assert audit.verify_chain() is True


# ---------------------------------------------------------------------------
# Restore failure — no handle to tear down, no downstream phases
# ---------------------------------------------------------------------------


async def test_restore_failure_short_circuits_and_never_teardowns() -> None:
    restore = FakeDbRestoreAdapter(
        restore_error=DbDrError(
            "substrate unavailable",
            experiment_id="exp-r",
            phase="restore",
            status_code=503,
        )
    )
    verifier, audit, restore_adapter, integrity, smoke = _make_verifier(restore=restore)

    verdict = await verifier.run(make_test_config(experiment_id="exp-r"))

    assert verdict.outcome is DbDrOutcome.RESTORE_FAILED
    assert verdict.handle is None
    assert verdict.error is not None and "substrate unavailable" in verdict.error

    # Downstream phases MUST NOT have been invoked.
    assert integrity.checked == []
    assert smoke.smoked == []
    # No handle → no teardown call.
    assert restore_adapter.torn_down == []

    kinds = _audit_kinds(audit)
    assert kinds == ["start", "restore_failed"]
    # There is intentionally NO teardown audit line here.
    assert "teardown_succeeded" not in kinds
    assert "teardown_failed" not in kinds


# ---------------------------------------------------------------------------
# Integrity failure — every mismatch is recorded, smoke never runs
# ---------------------------------------------------------------------------


async def test_any_integrity_mismatch_fails_the_run_and_records_every_mismatch() -> None:
    verifier, audit, restore, integrity, smoke = _make_verifier(
        integrity=FakeIntegrityChecker(report_sequence=(_mismatched_integrity(),)),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-int"))

    assert verdict.outcome is DbDrOutcome.INTEGRITY_FAILED
    assert verdict.integrity is not None
    assert verdict.integrity.mismatch_count == 2
    # Smoke MUST NOT have been invoked when integrity fails.
    assert smoke.smoked == []
    # Teardown ran exactly once — the environment is cleaned up.
    assert len(restore.torn_down) == 1

    integ = _find_audit_payload(audit, "integrity_failed")
    assert integ["mismatch_count"] == 2
    mismatches = integ["mismatches"]
    assert isinstance(mismatches, list) and len(mismatches) == 2
    kinds = {m["kind"] for m in mismatches}
    assert kinds == {"row_count", "checksum"}

    _assert_contains_in_order(
        _audit_kinds(audit),
        ["start", "integrity_failed", "teardown_succeeded"],
    )


async def test_single_mismatch_still_fails_the_run() -> None:
    # Explicitly validates "record it, don't average away" — one
    # mismatch out of many clean tables still trips INTEGRITY_FAILED.
    report = IntegrityReport(
        table_row_counts={"a": 1, "b": 2, "c": 3, "d": 4},
        checksums={"a": "x", "b": "y", "c": "z", "d": "w"},
        mismatches=(
            IntegrityMismatch(
                kind=IntegrityMismatchKind.FOREIGN_KEY,
                table="c",
                detail="fk_orders_users unresolved for 3 rows",
            ),
        ),
    )
    verifier, _audit, _restore, _integrity, smoke = _make_verifier(
        integrity=FakeIntegrityChecker(report_sequence=(report,)),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-fk"))

    assert verdict.outcome is DbDrOutcome.INTEGRITY_FAILED
    assert verdict.integrity is not None
    assert verdict.integrity.mismatch_count == 1
    assert smoke.smoked == []


# ---------------------------------------------------------------------------
# Smoke failure
# ---------------------------------------------------------------------------


async def test_smoke_failure_flips_outcome_and_records_failed_checks() -> None:
    verifier, audit, restore, _integrity, smoke = _make_verifier(
        smoke=FakeSmokeRunner(report_sequence=(_failing_smoke(),)),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-smk"))

    assert verdict.outcome is DbDrOutcome.SMOKE_FAILED
    assert verdict.smoke is not None
    assert verdict.smoke.passed is False
    assert len(verdict.smoke.failures) == 1
    assert len(smoke.smoked) == 1
    assert len(restore.torn_down) == 1

    payload = _find_audit_payload(audit, "smoke_failed")
    assert payload["failed_check_count"] == 1
    assert payload["failures"][0]["name"] == "insert-then-select"
    assert payload["checks_total"] == 2


async def test_empty_smoke_report_counts_as_failure() -> None:
    # An empty check list is not a passing signal — the runner is
    # misconfigured; the verifier surfaces this as SMOKE_FAILED so
    # the operator investigates rather than silently passing.
    verifier, _audit, _restore, _integrity, _smoke = _make_verifier(
        smoke=FakeSmokeRunner(report_sequence=(SmokeReport(checks=()),)),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-empty"))

    assert verdict.outcome is DbDrOutcome.SMOKE_FAILED
    assert verdict.smoke is not None and verdict.smoke.checks == ()


# ---------------------------------------------------------------------------
# Rollback-on-abort — exceptions in later phases tear the environment down
# ---------------------------------------------------------------------------


async def test_integrity_exception_aborts_and_tears_down() -> None:
    verifier, audit, restore, _integrity, smoke = _make_verifier(
        integrity=FakeIntegrityChecker(
            check_error=RuntimeError("checker crashed mid-scan"),
        ),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-abort-int"))

    assert verdict.outcome is DbDrOutcome.ABORTED
    assert verdict.error is not None and "checker crashed" in verdict.error
    assert smoke.smoked == []
    assert len(restore.torn_down) == 1

    payload = _find_audit_payload(audit, "aborted")
    assert payload["phase"] == "integrity"
    _assert_contains_in_order(
        _audit_kinds(audit),
        ["start", "aborted", "teardown_succeeded"],
    )


async def test_smoke_exception_aborts_and_tears_down() -> None:
    verifier, audit, restore, _integrity, _smoke = _make_verifier(
        smoke=FakeSmokeRunner(run_error=RuntimeError("smoke transport error")),
    )

    verdict = await verifier.run(make_test_config(experiment_id="exp-abort-smk"))

    assert verdict.outcome is DbDrOutcome.ABORTED
    assert verdict.error is not None and "smoke transport error" in verdict.error
    assert len(restore.torn_down) == 1

    payload = _find_audit_payload(audit, "aborted")
    assert payload["phase"] == "smoke"


async def test_teardown_error_is_recorded_but_does_not_change_primary_outcome() -> None:
    restore = FakeDbRestoreAdapter(
        teardown_error=DbDrError(
            "delete rg 500",
            experiment_id="exp-td",
            phase="teardown",
            status_code=500,
        )
    )
    verifier, audit, restore_adapter, _integrity, _smoke = _make_verifier(restore=restore)

    verdict = await verifier.run(make_test_config(experiment_id="exp-td"))

    # Primary outcome is unchanged.
    assert verdict.outcome is DbDrOutcome.PASSED
    # Teardown was attempted (single call — the injected error clears
    # after firing so the fake does not spin) but the failure was
    # audited.
    assert restore_adapter.torn_down == []
    payload = _find_audit_payload(audit, "teardown_failed")
    assert "delete rg 500" in payload["error"]
    assert "teardown_succeeded" not in _audit_kinds(audit)


async def test_integrity_report_default_isolates_mismatches_field() -> None:
    # Cross-check: a report constructed without an explicit mismatches
    # tuple is trivially clean, so the verifier's happy path does not
    # depend on the checker spelling out an empty tuple.
    report = IntegrityReport(table_row_counts={"a": 1}, checksums={"a": "x"})
    assert report.is_clean is True
    assert report.mismatch_count == 0

    verifier, _audit, _restore, _integrity, smoke = _make_verifier(
        integrity=FakeIntegrityChecker(report_sequence=(report,)),
    )
    verdict = await verifier.run(make_test_config(experiment_id="exp-defaults"))
    assert verdict.outcome is DbDrOutcome.PASSED
    assert len(smoke.smoked) == 1


# ---------------------------------------------------------------------------
# SmokeReport / IntegrityReport property-level assertions
# ---------------------------------------------------------------------------


def test_smoke_report_passed_property_requires_non_empty_checks() -> None:
    assert SmokeReport(checks=()).passed is False


def test_smoke_report_failures_preserves_order() -> None:
    r = SmokeReport(
        checks=(
            SmokeCheck(name="a", passed=False),
            SmokeCheck(name="b", passed=True),
            SmokeCheck(name="c", passed=False),
        )
    )
    assert [c.name for c in r.failures] == ["a", "c"]


def test_integrity_report_helpers() -> None:
    r = _mismatched_integrity()
    assert r.mismatch_count == 2
    assert r.is_clean is False
    assert _clean_integrity().is_clean is True


# ---------------------------------------------------------------------------
# DbDrError formatting sanity
# ---------------------------------------------------------------------------


def test_db_dr_error_formats_experiment_id_and_phase() -> None:
    with pytest.raises(DbDrError) as excinfo:
        raise DbDrError("boom", experiment_id="e-1", phase="restore", status_code=500)
    msg = str(excinfo.value)
    assert "boom" in msg
    assert "e-1" in msg
    assert "restore" in msg
    assert "HTTP 500" in msg


def test_db_dr_error_without_status_code() -> None:
    err = DbDrError("no status", experiment_id="e-2", phase="smoke")
    assert err.status_code is None
    assert "HTTP" not in str(err)


# ---------------------------------------------------------------------------
# Helper coverage — naive datetime + long error string
# ---------------------------------------------------------------------------


async def test_naive_point_in_time_is_serialized_as_utc_in_start_audit() -> None:
    verifier, audit, *_ = _make_verifier()
    naive = datetime(2026, 7, 6, 12, 34, 56)  # noqa: DTZ001 — intentional
    config = DbRestoreConfig(
        experiment_id="exp-naive",
        source_ref=(
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/rg-source/providers/Microsoft.DBforPostgreSQL/"
            "flexibleServers/src"
        ),
        target_server_name="tgt",
        target_resource_group="rg-tgt",
        target_location="koreacentral",
        point_in_time_utc=naive,
    )
    await verifier.run(config)
    start = _find_audit_payload(audit, "start")
    assert start["point_in_time_utc"] is not None
    assert start["point_in_time_utc"].startswith("2026-07-06T12:34:56")
    # ISO with a UTC offset ("+00:00" from astimezone(UTC).isoformat()).
    assert "+00:00" in start["point_in_time_utc"]


async def test_long_error_message_is_truncated_in_audit_payload() -> None:
    long_msg = "X" * 500
    restore = FakeDbRestoreAdapter(restore_error=RuntimeError(long_msg))
    verifier, audit, *_ = _make_verifier(restore=restore)

    verdict = await verifier.run(make_test_config(experiment_id="exp-long"))

    assert verdict.outcome is DbDrOutcome.RESTORE_FAILED
    assert verdict.error is not None
    # Truncation cap is 200 + ellipsis.
    assert len(verdict.error) <= 201
    assert verdict.error.endswith("…")
    payload = _find_audit_payload(audit, "restore_failed")
    assert payload["error"].endswith("…")
