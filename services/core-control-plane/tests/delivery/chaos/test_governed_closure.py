"""Target claims release only verified outcomes; everything else needs a separate closure."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.run_store import ChaosRunStore
from fdai.core.recovery import RecoveryProbeKind
from fdai.delivery.chaos.governed_bindings import ChaosApprovalEvidence
from fdai.delivery.chaos.governed_claims import closure_record_key, target_digest
from fdai.delivery.chaos.governed_closure import GovernedChaosClosure
from fdai.delivery.chaos.governed_records import governed_chaos_run_id
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import ToolCallOutcome

from tests.delivery.chaos.governed_doubles import (
    RUN_ID,
    SCENARIO_ID,
    EvidenceCollector,
    Injector,
    LostLock,
)
from tests.delivery.chaos.governed_fixtures import (
    GovernedFixture,
    audit_kinds,
    enforce_request,
    governed_fixture,
)

_REASON = "operator verified the fault is absent and the workload recovered"
_CLOSURE_REF = "closure-1"


def _closure(
    run_id: str = RUN_ID,
    *,
    approval_ref: str = _CLOSURE_REF,
    principal: str = "Var",
    approvers: tuple[str, ...] = ("approver-b",),
    initiator: str = "operator-c",
    intent: str = "closure",
    targets: tuple[str, ...] = ("pod-a",),
) -> ChaosApprovalEvidence:
    return ChaosApprovalEvidence(
        approval_ref=approval_ref,
        approval_principal=principal,
        approver_ids=approvers,
        initiator_id=initiator,
        intent=intent,
        run_id=run_id,
        target_digests=tuple(target_digest(item) for item in targets),
    )


class _ProcessStopped(BaseException):
    """Simulates the operator process exiting while a fault is live."""


async def _stop_process(_seconds: float) -> None:
    raise _ProcessStopped


class _PausedAfterApproval(InMemoryStateStore):
    """Pauses the runner right after ``approved`` so a closure can land mid-flight."""

    def __init__(self) -> None:
        super().__init__()
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        applied = await super().compare_and_set_state_with_audit(
            key, value, expected_revision=expected_revision, audit_entry=audit_entry
        )
        if applied and value.get("state") == ChaosRunState.APPROVED.value:
            self.reached.set()
            await self.release.wait()
        return applied


async def _first_run(store: InMemoryStateStore, **overrides: Any) -> tuple[str | None, bool | None]:
    first = governed_fixture(state_store=store, **overrides)
    receipt = await first.adapter.execute(enforce_request())
    return receipt.detail, receipt.rollback_succeeded


async def _second_run(store: InMemoryStateStore) -> tuple[GovernedFixture, ToolCallOutcome, str]:
    second = governed_fixture(state_store=store)
    receipt = await second.adapter.execute(enforce_request(key="chaos-key-2"))
    return second, receipt.outcome, receipt.detail or ""


def _closer(
    store: InMemoryStateStore, **overrides: Any
) -> tuple[GovernedFixture, GovernedChaosClosure]:
    closer = governed_fixture(state_store=store, **overrides)
    return closer, GovernedChaosClosure(bindings=closer.bindings)


@pytest.mark.parametrize(
    ("overrides", "first_detail"),
    [
        pytest.param(
            {"injector": Injector(stop_fails=True)},
            "failed:rollback_failed",
            id="failed-after-injection",
        ),
        pytest.param(
            {"collector": EvidenceCollector(omit=RecoveryProbeKind.FAULT_ABSENT)},
            "escalated:unscorable",
            id="escalated",
        ),
        pytest.param(
            {
                "injector": Injector(applied_then_timeout=True),
                "collector": EvidenceCollector(omit=RecoveryProbeKind.FAULT_ABSENT),
            },
            "stopped:aborted:escalated",
            id="applied-then-timeout-unverified",
        ),
    ],
)
async def test_unverified_runs_keep_their_targets_claimed(
    overrides: dict[str, Any],
    first_detail: str,
) -> None:
    store = InMemoryStateStore()

    detail, rollback = await _first_run(store, **overrides)
    second, outcome, second_detail = await _second_run(store)

    assert detail == first_detail
    assert rollback is False
    assert outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert "conflicting_work_open" in second_detail
    assert second.injector.injected == []


@pytest.mark.parametrize(
    ("overrides", "first_detail"),
    [
        pytest.param({}, "recovered:validated", id="recovered"),
        pytest.param({"approval": None}, "denied:", id="denied"),
        pytest.param(
            {"injector": Injector(fault_type="other")},
            "failed:aborted",
            id="failed-without-an-injection-attempt",
        ),
        pytest.param(
            {"injector": Injector(applied_then_timeout=True)},
            "stopped:aborted:recovered",
            id="applied-then-timeout-independently-verified",
        ),
    ],
)
async def test_verified_outcomes_release_their_targets(
    overrides: dict[str, Any],
    first_detail: str,
) -> None:
    store = InMemoryStateStore()

    detail, _rollback = await _first_run(store, **overrides)
    second, outcome, _detail = await _second_run(store)

    assert detail is not None and detail.startswith(first_detail)
    assert outcome is ToolCallOutcome.SUCCEEDED
    assert second.injector.injected == ["pod-a"]


async def test_applied_then_timeout_injection_is_rolled_back_and_recovered() -> None:
    store = InMemoryStateStore()
    first = governed_fixture(state_store=store, injector=Injector(applied_then_timeout=True))

    receipt = await first.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert receipt.rollback_succeeded is True
    assert first.injector.stopped == ["pod-a"]
    assert first.dispatcher.calls == ["restore"]


async def test_separate_closure_releases_an_escalated_run_and_it_never_resumes() -> None:
    store = InMemoryStateStore()
    await _first_run(store, collector=EvidenceCollector(omit=RecoveryProbeKind.FAULT_ABSENT))
    closer, closure = _closer(store)
    closer.verifier.closure = _closure()

    closed = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    again = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    retried = await closer.adapter.execute(enforce_request())
    second, outcome, _detail = await _second_run(store)

    assert [(item.run_id, item.closed, item.reason) for item in closed] == [
        (RUN_ID, True, "closed")
    ]
    assert [item.reason for item in again] == ["already_closed"]
    request = closer.verifier.closure_requests[0]
    assert request.metadata["intent"] == "closure"
    assert request.arguments["closure_of_run_id"] == RUN_ID
    record = await store.read_state(closure_record_key(RUN_ID))
    assert record is not None and record["approver_ids"] == ["approver-b"]
    assert audit_kinds(closer).count("chaos.run.closure") == 1
    assert retried.detail == "closed:human_closure"
    assert outcome is ToolCallOutcome.SUCCEEDED
    assert second.injector.injected == ["pod-a"]


async def test_closure_refuses_the_approval_that_authorized_the_injection() -> None:
    store = InMemoryStateStore()
    await _first_run(store, injector=Injector(stop_fails=True))
    closer, closure = _closer(store)
    closer.verifier.closure = _closure(approval_ref="approval-1")

    results = await closure.close_targets(
        targets=("pod-a",), approval_ref="approval-1", reason=_REASON
    )
    second, outcome, _detail = await _second_run(store)

    assert [(item.closed, item.reason) for item in results] == [
        (False, "closure_reuses_enforce_approval")
    ]
    assert closer.verifier.closure_requests == []
    assert "chaos.run.closure.refused" in audit_kinds(closer)
    assert outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert second.injector.injected == []


@pytest.mark.parametrize(
    ("evidence", "refusal"),
    [
        pytest.param(
            _closure(approvers=("operator-c",)), "self_approval_forbidden", id="self-approval"
        ),
        pytest.param(_closure(principal="Loki"), "var_approval_required", id="not-var"),
        pytest.param(
            _closure(approval_ref="closure-other"), "approval_unverified", id="claim-mismatch"
        ),
        pytest.param(_closure(approvers=()), "approval_quorum_not_met", id="no-approver"),
        pytest.param(_closure(intent="enforce"), "closure_intent_missing", id="enforce-intent"),
        pytest.param(_closure(run_id="other-run"), "closure_scope_mismatch", id="other-run"),
        pytest.param(_closure(targets=("pod-b",)), "closure_scope_mismatch", id="other-targets"),
        pytest.param(None, "approval_unverified", id="no-approval"),
    ],
)
async def test_closure_refuses_without_a_distinct_var_closure_decision(
    evidence: ChaosApprovalEvidence | None,
    refusal: str,
) -> None:
    store = InMemoryStateStore()
    await _first_run(store, injector=Injector(stop_fails=True))
    closer, closure = _closer(store)
    closer.verifier.closure = evidence

    results = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    second, outcome, detail = await _second_run(store)

    assert [(item.closed, item.reason) for item in results] == [(False, refusal)]
    assert await store.read_state(closure_record_key(RUN_ID)) is None
    assert "chaos.run.closure.refused" in audit_kinds(closer)
    assert outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert "conflicting_work_open" in detail
    assert second.injector.injected == []


async def test_closure_by_target_releases_an_orphan_whose_request_is_lost() -> None:
    store = InMemoryStateStore()
    orphan = governed_fixture(state_store=store, sleeper=_stop_process)
    with pytest.raises(_ProcessStopped):
        await orphan.adapter.execute(enforce_request(key="lost-key"))
    lost_run = governed_chaos_run_id("lost-key", SCENARIO_ID, ("pod-a",))
    closer, closure = _closer(store)
    closer.verifier.closure = _closure(lost_run)

    results = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    resumed = await closer.adapter.execute(enforce_request(key="lost-key"))
    second, outcome, _detail = await _second_run(store)

    snapshot = await ChaosRunStore(state_store=store).get(lost_run)
    assert [(item.run_id, item.closed) for item in results] == [(lost_run, True)]
    assert snapshot is not None and snapshot.state is ChaosRunState.OBSERVING
    assert resumed.detail == "closed:human_closure"
    assert closer.dispatcher.calls == []
    assert outcome is ToolCallOutcome.SUCCEEDED
    assert second.injector.injected == ["pod-a"]


async def test_a_run_closed_mid_flight_never_injects_even_without_lock_exclusion() -> None:
    store = _PausedAfterApproval()
    runner = governed_fixture(state_store=store, lock=LostLock())
    task = asyncio.create_task(runner.adapter.execute(enforce_request()))
    await asyncio.wait_for(store.reached.wait(), timeout=5)
    closer, closure = _closer(store, lock=LostLock())
    closer.verifier.closure = _closure()

    results = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    store.release.set()
    receipt = await asyncio.wait_for(task, timeout=5)

    snapshot = await ChaosRunStore(state_store=store).get(RUN_ID)
    assert [(item.closed, item.reason) for item in results] == [(True, "closed")]
    assert receipt.outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert receipt.detail == "conflict:run_closed"
    assert snapshot is not None and snapshot.state is ChaosRunState.DENIED
    assert runner.injector.injected == []


async def test_closure_leaves_released_or_unclaimed_targets_untouched() -> None:
    store = InMemoryStateStore()
    closer, closure = _closer(store)

    unclaimed = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )
    await closer.adapter.execute(enforce_request())
    released = await closure.close_targets(
        targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=_REASON
    )

    assert [item.reason for item in unclaimed] == ["no_claim"]
    assert [item.reason for item in released] == ["already_released"]
    assert closer.verifier.closure_requests == []
    with pytest.raises(ValueError, match="reason"):
        await closure.close_targets(targets=("pod-a",), approval_ref=_CLOSURE_REF, reason=" ")
