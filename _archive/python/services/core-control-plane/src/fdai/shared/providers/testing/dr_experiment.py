"""In-memory :class:`DrExperimentRunner` for unit tests + debugger sessions.

Ships in the main package (not under ``tests/``) so a fork MAY reuse
it as a lightweight backend for a local, throwaway environment. It is
**not** suitable for production - runs vanish on process restart, and
there is no real substrate interaction.

Behavior matrix
---------------

The fake tracks every started run in a dictionary keyed by
``handle.run_id`` and supports three test knobs:

- :attr:`FakeDrExperimentRunner.start_error` - if set, ``start`` raises
  it exactly once (then clears). Simulates a 4xx / auth failure.
- :attr:`FakeDrExperimentRunner.check_error` - if set, ``check`` raises
  it exactly once. Simulates a substrate glitch that trips rollback.
- :attr:`FakeDrExperimentRunner.status_sequence` - pre-programmed
  :class:`DrRunStatus` values consumed by successive ``check`` calls;
  the last value is repeated. Defaults to a single ``SUCCEEDED``.

The observable state (``started`` / ``checked`` / ``rolled_back`` counts,
per-experiment status history) is exposed as attributes so tests can
assert on it without reaching into private members.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from fdai.core.verticals.resilience import DrExperiment
from fdai.shared.providers.dr_experiment import (
    DrExperimentKind,
    DrExperimentRunner,
    DrRunHandle,
    DrRunStatus,
)


class FakeDrExperimentRunner(DrExperimentRunner):
    """Deterministic, in-memory :class:`DrExperimentRunner`.

    Every operation is synchronous under the hood; the ``async``
    signatures match the Protocol so callers exercise the real
    control-flow paths (``await``) unchanged.
    """

    def __init__(
        self,
        *,
        kind: DrExperimentKind = DrExperimentKind.CHAOS,
        status_sequence: Sequence[DrRunStatus] = (DrRunStatus.SUCCEEDED,),
        start_error: BaseException | None = None,
        check_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
    ) -> None:
        if not status_sequence:
            raise ValueError("status_sequence MUST NOT be empty")
        self._kind = kind
        self._status_sequence = tuple(status_sequence)
        self._start_error = start_error
        self._check_error = check_error
        self._rollback_error = rollback_error

        # Observable state - deliberately public.
        self.started: list[DrRunHandle] = []
        self.checked: list[DrRunHandle] = []
        self.rolled_back: list[DrRunHandle] = []
        self._check_index: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # DrExperimentRunner Protocol
    # ------------------------------------------------------------------

    async def start(self, experiment: DrExperiment) -> DrRunHandle:
        if self._start_error is not None:
            error = self._start_error
            self._start_error = None
            raise error

        provider_ref = experiment.provider_ref or f"fake:{experiment.experiment_id}"
        handle = DrRunHandle(
            experiment_id=experiment.experiment_id,
            kind=self._kind,
            provider_ref=provider_ref,
            run_id=f"fake-run-{uuid.uuid4()}",
            started_at=datetime.now(tz=UTC),
            status_url=None,
        )
        self.started.append(handle)
        return handle

    async def check(self, handle: DrRunHandle) -> DrRunStatus:
        if self._check_error is not None:
            error = self._check_error
            self._check_error = None
            raise error

        self.checked.append(handle)
        idx = self._check_index[handle.run_id]
        if idx >= len(self._status_sequence):
            idx = len(self._status_sequence) - 1
        else:
            self._check_index[handle.run_id] = idx + 1
        return self._status_sequence[idx]

    async def rollback(self, handle: DrRunHandle) -> None:
        if self._rollback_error is not None:
            error = self._rollback_error
            self._rollback_error = None
            raise error
        # Idempotent: repeated rollback of the same handle is a no-op
        # observationally (we still record the call so tests can count).
        self.rolled_back.append(handle)


__all__ = ["FakeDrExperimentRunner"]
