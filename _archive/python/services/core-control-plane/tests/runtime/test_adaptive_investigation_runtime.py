from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rca.discrimination import build_hypothesis_discrimination_frame
from fdai.core.read_investigation.adaptive import AdaptiveRoundProposal
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
)
from fdai.core.read_investigation.adaptive_process import (
    project_adaptive_investigation_room,
)
from fdai.runtime.adaptive_investigation_runtime import AdaptiveInvestigationRuntime
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

NOW = datetime(2026, 8, 30, tzinfo=UTC)
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"


class _NoCandidateSource:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, frame):
        self.calls += 1
        return AdaptiveRoundProposal(
            frame_digest=frame.frame_digest,
            candidates=(),
            bindings=(),
        )


class _UnusedReviser:
    async def revise(self, *, frame, execution):
        raise AssertionError("held selection must not revise hypotheses")


class _CancellingSource:
    def __init__(self, cancelled) -> None:
        self.cancelled = cancelled

    async def propose(self, frame):
        self.cancelled.set()
        return AdaptiveRoundProposal(
            frame_digest=frame.frame_digest,
            candidates=(),
            bindings=(),
        )


class _FailingSource:
    async def propose(self, frame):
        raise RuntimeError("proposal failed")


def test_runtime_module_imports_in_cold_process() -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (
                "services/core-control-plane/src",
                "packages/service-contracts/src",
            )
        ),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fdai.runtime.adaptive_investigation_runtime "
                "import AdaptiveInvestigationRuntime; "
                "print(AdaptiveInvestigationRuntime.__name__)"
            ),
        ],
        check=False,
        capture_output=True,
        cwd=".",
        env=environment,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "AdaptiveInvestigationRuntime"


async def test_runtime_persists_held_session_before_returning() -> None:
    store = InMemoryProcessRuntimeStore()
    source = _NoCandidateSource()
    frame = build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision="graph-1",
        evidence_cutoff=NOW,
        active_hypothesis_ids=("hypothesis-a", "hypothesis-b"),
        active_set_receipt_digest=DIGEST_A,
        cost_model_digest=DIGEST_B,
    )
    runtime = AdaptiveInvestigationRuntime(
        process_store=store,
        round_source=source,
        reviser=_UnusedReviser(),
        gateway=object(),  # type: ignore[arg-type]
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await runtime.run(
        session_id="adaptive-1",
        target_resource_id="resource-1",
        correlation_id="correlation-1",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=2,
            max_queries=2,
            max_cost_units=10,
            deadline_at=NOW + timedelta(minutes=1),
            policy_digest=DIGEST_B,
        ),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    snapshot = await store.get("adaptive-1")
    assert snapshot is not None
    assert snapshot.status is ProcessStatus.SUCCEEDED
    room = project_adaptive_investigation_room(await store.events("adaptive-1"))
    assert room is not None
    assert room["round_count"] == 1
    assert source.calls == 1

    replayed = await runtime.run(
        session_id="adaptive-1",
        target_resource_id="resource-1",
        correlation_id="correlation-1",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=2,
            max_queries=2,
            max_cost_units=10,
            deadline_at=NOW + timedelta(minutes=1),
            policy_digest=DIGEST_B,
        ),
    )
    assert replayed.result_digest == result.result_digest
    assert source.calls == 1


async def test_runtime_closes_process_when_cancelled_during_proposal() -> None:
    store = InMemoryProcessRuntimeStore()
    cancelled = asyncio.Event()
    frame = build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision="graph-1",
        evidence_cutoff=NOW,
        active_hypothesis_ids=("hypothesis-a", "hypothesis-b"),
        active_set_receipt_digest=DIGEST_A,
        cost_model_digest=DIGEST_B,
    )
    runtime = AdaptiveInvestigationRuntime(
        process_store=store,
        round_source=_CancellingSource(cancelled),
        reviser=_UnusedReviser(),
        gateway=object(),  # type: ignore[arg-type]
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    result = await runtime.run(
        session_id="adaptive-cancel",
        target_resource_id="resource-1",
        correlation_id="correlation-1",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=2,
            max_queries=2,
            max_cost_units=10,
            deadline_at=NOW + timedelta(minutes=1),
            policy_digest=DIGEST_B,
        ),
        cancelled=cancelled,
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CANCELLED
    assert result.used_queries == 0
    snapshot = await store.get("adaptive-cancel")
    assert snapshot is not None
    assert snapshot.status is ProcessStatus.CANCELLED


async def test_runtime_failure_closes_process_before_reraising() -> None:
    store = InMemoryProcessRuntimeStore()
    frame = build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision="graph-1",
        evidence_cutoff=NOW,
        active_hypothesis_ids=("hypothesis-a", "hypothesis-b"),
        active_set_receipt_digest=DIGEST_A,
        cost_model_digest=DIGEST_B,
    )
    runtime = AdaptiveInvestigationRuntime(
        process_store=store,
        round_source=_FailingSource(),
        reviser=_UnusedReviser(),
        gateway=object(),  # type: ignore[arg-type]
        active_strategy_digest=DIGEST_A,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="proposal failed"):
        await runtime.run(
            session_id="adaptive-failed",
            target_resource_id="resource-1",
            correlation_id="correlation-1",
            initial_frame=frame,
            budget=AdaptiveInvestigationBudget(
                max_rounds=2,
                max_queries=2,
                max_cost_units=10,
                deadline_at=NOW + timedelta(minutes=1),
                policy_digest=DIGEST_B,
            ),
        )

    snapshot = await store.get("adaptive-failed")
    assert snapshot is not None
    assert snapshot.status is ProcessStatus.FAILED
