"""In-memory Deep DB-DR fakes for unit tests + debugger sessions.

Ships in the main package (not under ``tests/``) so a fork MAY reuse
these fakes as a lightweight backend for a local, throwaway
environment. They are **not** suitable for production - no real
substrate interaction happens.

Every fake exposes the observable state as public attributes so tests
can assert on ``restored`` / ``torn_down`` / ``checked`` / ``smoked``
without reaching into private members. Error injection knobs let a
test simulate a transport failure exactly once per phase.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from fdai.shared.providers.db_dr import (
    DbRestoreAdapter,
    DbRestoreConfig,
    DbRestoreHandle,
    IntegrityChecker,
    IntegrityReport,
    SmokeReport,
    SmokeRunner,
)

_DEFAULT_ENDPOINT: Final[str] = "fake-restore.example.internal"


class FakeDbRestoreAdapter(DbRestoreAdapter):
    """Deterministic, in-memory :class:`DbRestoreAdapter`.

    ``restore`` records the config, mints a synthetic ARM id, and
    returns a handle. ``teardown`` records the handle. Both operations
    are one-shot error-injectable: the first call after ``restore_error``
    (or ``teardown_error``) is set raises that exception exactly once,
    then the knob clears.
    """

    def __init__(
        self,
        *,
        restore_error: BaseException | None = None,
        teardown_error: BaseException | None = None,
        endpoint: str = _DEFAULT_ENDPOINT,
    ) -> None:
        self._restore_error = restore_error
        self._teardown_error = teardown_error
        self._endpoint = endpoint

        # Observable state - deliberately public.
        self.restored: list[DbRestoreConfig] = []
        self.torn_down: list[DbRestoreHandle] = []

    async def restore(self, config: DbRestoreConfig) -> DbRestoreHandle:
        if self._restore_error is not None:
            error = self._restore_error
            self._restore_error = None
            raise error

        self.restored.append(config)
        target_ref = (
            f"/subscriptions/00000000-0000-0000-0000-000000000000/"
            f"resourceGroups/{config.target_resource_group}/providers/"
            f"Microsoft.DBforPostgreSQL/flexibleServers/{config.target_server_name}"
        )
        return DbRestoreHandle(
            experiment_id=config.experiment_id,
            source_ref=config.source_ref,
            target_ref=target_ref,
            endpoint=f"{config.target_server_name}.{self._endpoint}",
            resource_group=config.target_resource_group,
            created_at=datetime.now(tz=UTC),
        )

    async def teardown(self, handle: DbRestoreHandle) -> None:
        if self._teardown_error is not None:
            error = self._teardown_error
            self._teardown_error = None
            raise error
        # Idempotent: repeated teardown of the same handle is recorded
        # but does not raise.
        self.torn_down.append(handle)


class FakeIntegrityChecker(IntegrityChecker):
    """Return pre-programmed :class:`IntegrityReport` values.

    ``report_sequence`` supports scenario tests that need distinct
    verdicts on successive runs; the last value is repeated so a test
    that only wires one report gets it back on every call.
    """

    def __init__(
        self,
        *,
        report_sequence: Sequence[IntegrityReport] = (),
        check_error: BaseException | None = None,
    ) -> None:
        if not report_sequence and check_error is None:
            # Default: a trivially clean report so happy-path tests
            # don't have to spell one out.
            report_sequence = (IntegrityReport(table_row_counts={}, checksums={}),)
        self._report_sequence: tuple[IntegrityReport, ...] = tuple(report_sequence)
        self._check_error = check_error

        self.checked: list[DbRestoreHandle] = []
        self._index = 0

    async def check(self, handle: DbRestoreHandle) -> IntegrityReport:
        if self._check_error is not None:
            error = self._check_error
            self._check_error = None
            raise error

        self.checked.append(handle)
        if self._index >= len(self._report_sequence):
            idx = len(self._report_sequence) - 1
        else:
            idx = self._index
            self._index += 1
        return self._report_sequence[idx]


class FakeSmokeRunner(SmokeRunner):
    """Return pre-programmed :class:`SmokeReport` values."""

    def __init__(
        self,
        *,
        report_sequence: Sequence[SmokeReport] = (),
        run_error: BaseException | None = None,
    ) -> None:
        self._report_sequence: tuple[SmokeReport, ...] = tuple(report_sequence)
        self._run_error = run_error

        self.smoked: list[DbRestoreHandle] = []
        self._index = 0

    async def run(self, handle: DbRestoreHandle) -> SmokeReport:
        if self._run_error is not None:
            error = self._run_error
            self._run_error = None
            raise error

        self.smoked.append(handle)
        if not self._report_sequence:
            return SmokeReport(checks=())
        if self._index >= len(self._report_sequence):
            idx = len(self._report_sequence) - 1
        else:
            idx = self._index
            self._index += 1
        return self._report_sequence[idx]


def make_test_config(
    *,
    experiment_id: str | None = None,
    target_server_name: str | None = None,
    source_ref: str | None = None,
    target_resource_group: str | None = None,
    target_location: str = "koreacentral",
) -> DbRestoreConfig:
    """Convenience factory for tests - assembles a valid config.

    Every field defaults to a synthetic, customer-agnostic value so
    tests stay self-contained; callers override only what they care
    about.
    """
    exp = experiment_id or f"exp-{uuid.uuid4()}"
    default_source = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/rg-source/providers/Microsoft.DBforPostgreSQL/"
        "flexibleServers/src-server"
    )
    return DbRestoreConfig(
        experiment_id=exp,
        source_ref=source_ref or default_source,
        target_server_name=target_server_name or f"restored-{exp}",
        target_resource_group=target_resource_group or f"rg-restored-{exp}",
        target_location=target_location,
    )


__all__ = [
    "FakeDbRestoreAdapter",
    "FakeIntegrityChecker",
    "FakeSmokeRunner",
    "make_test_config",
]
