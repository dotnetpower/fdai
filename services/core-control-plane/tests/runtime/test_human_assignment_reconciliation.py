from __future__ import annotations

from fdai.core.human_assignment import AssignmentReconciler
from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_worker_observes_no_cases_from_empty_store() -> None:
    worker = AssignmentReconciliationWorker(
        reconciler=AssignmentReconciler(store=InMemoryStateStore()),
        interval_seconds=1,
    )

    assert await worker.run_once() == 0
