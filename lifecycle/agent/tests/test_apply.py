"""Apply mode: two-stage audit, rollout verification, rollback, idempotency, and resumption."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fdai_deployment_cli.lifecycle_plan import (
    LifecyclePhaseCompletionReceipt,
    exact_plan_digest_for,
    issue_lifecycle_authorization_receipt,
)

from fdai_lifecycle_agent.dry_run import Health, load_current_state
from fdai_lifecycle_agent.hub_client import HubProtocolError, PlanReport
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.workload import Manifest, render

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness


def _image(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


V1, V2, V3 = _image("v1"), _image("v2"), _image("v3-missing")


def _outcomes(harness: Harness) -> list[tuple[int, str, str]]:
    return [
        (report.attempt, report.outcome, report.reason_code) for _, _, report in harness.hub.reports
    ]


def _store(harness: Harness) -> WorkloadStore:
    return WorkloadStore(harness.state_store.path.parent)


def _upgrade_to_v2(harness: Harness, cluster: FakeCluster) -> None:
    """Apply v1 then v2 healthily, leaving v2 as the recorded healthy rendering."""

    for sequence, (version, digest) in enumerate((("1.0.0", V1), ("1.1.0", V2)), start=8):
        harness.serve(harness.release_plan(version, digest, sequence=sequence))
        assert harness.apply_poll(cluster).outcome == "applied"
    harness.hub.reports.clear()
    harness.hub.states.clear()


def test_apply_reports_started_then_applied_and_a_verifiable_snapshot(
    harness: Harness, cluster: FakeCluster
) -> None:
    plan = harness.serve(harness.release_plan("1.0.0", V1))

    result = harness.apply_poll(cluster)

    digest = "sha256:" + hashlib.sha256(plan.signed_payload).hexdigest()
    assert (result.outcome, result.reported, result.exact_plan_digest) == ("applied", True, digest)
    assert _outcomes(harness) == [(1, "apply-started", "apply_started"), (2, "applied", "applied")]
    assert {report.exact_plan_digest for _, _, report in harness.hub.reports} == {digest}
    assert cluster.image() == f"{harness.repository}@{V1}"
    [snapshot] = harness.hub.states
    content = {key: value for key, value in snapshot.items() if key != "digest"}
    assert (
        snapshot["digest"]
        == hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert snapshot["entities"]["core"] == {  # type: ignore[index]
        "release_id": "1.0.0",
        "artifact_digests": [V1],
        "health": "healthy",
    }
    assert json.loads(harness.state_file.read_text()) == snapshot
    assert _store(harness).load().journal is None


def test_the_next_plan_is_admitted_against_the_reported_snapshot(
    harness: Harness, cluster: FakeCluster
) -> None:

    _upgrade_to_v2(harness, cluster)

    assert cluster.image() == f"{harness.repository}@{V2}"
    assert load_current_state(harness.state_file).entities["core"].release_id == "1.1.0"


def test_an_applied_plan_is_never_applied_again(harness: Harness, cluster: FakeCluster) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    harness.apply_poll(cluster)
    writes = len(cluster.writes())

    again = harness.apply_poll(cluster)

    assert again.outcome == "already-reported"
    assert len(cluster.writes()) == writes
    assert len(harness.hub.reports) == 2


def test_failed_health_check_rolls_back_to_the_last_healthy_rendering(
    harness: Harness, cluster: FakeCluster
) -> None:
    cluster.broken_images.add(f"{harness.repository}@{V3}")
    _upgrade_to_v2(harness, cluster)
    before = load_current_state(harness.state_file)
    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))

    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code, result.reported) == (
        "rolled-back",
        "health_check_failed",
        True,
    )
    assert _outcomes(harness) == [
        (1, "apply-started", "apply_started"),
        (2, "rolled-back", "health_check_failed"),
    ]
    assert json.loads(harness.hub.reports[-1][2].summary)["rollback"] == "verified"
    assert cluster.image() == f"{harness.repository}@{V2}"
    after = load_current_state(harness.state_file)
    assert after.entities == before.entities
    assert after.observed_at > before.observed_at
    assert [snapshot["digest"] for snapshot in harness.hub.states] == [after.digest]


def test_failed_apply_rolls_back_with_apply_failed(harness: Harness, cluster: FakeCluster) -> None:
    cluster.failing_images.add(f"{harness.repository}@{V3}")
    _upgrade_to_v2(harness, cluster)
    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))

    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    assert cluster.image() == f"{harness.repository}@{V2}"


def test_failed_rollback_halts_every_later_apply(harness: Harness, cluster: FakeCluster) -> None:
    cluster.broken_images.add(f"{harness.repository}@{V3}")
    _upgrade_to_v2(harness, cluster)
    cluster.failing_images.add(f"{harness.repository}@{V2}")
    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))

    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code) == ("rolled-back", "health_check_failed")
    assert json.loads(harness.hub.reports[-1][2].summary)["rollback"] == "failed"
    assert load_current_state(harness.state_file).entities["core"].health == "unhealthy"
    assert _store(harness).halted_plan_id() == "plan-0010"

    harness.serve(harness.release_plan("1.1.0", V2, sequence=11))
    writes, fetches = len(cluster.writes()), harness.hub.fetches
    halted = harness.apply_poll(cluster)

    assert (halted.outcome, halted.reason_code, halted.plan_id) == (
        "halted",
        "rollback_failed",
        "plan-0010",
    )
    assert (len(cluster.writes()), harness.hub.fetches) == (writes, fetches)


def test_nothing_is_applied_until_the_hub_accepts_apply_started(
    harness: Harness, cluster: FakeCluster
) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    harness.hub.report_errors.append(HubProtocolError("Hub report request returned 503"))

    first = harness.apply_poll(cluster)

    assert (first.outcome, first.reported) == ("apply-started", False)
    assert cluster.writes() == []

    second = harness.apply_poll(cluster)

    assert second.outcome == "applied"
    assert [report.attempt for report in harness.hub.attempted] == [1, 1, 2]
    assert _outcomes(harness) == [(1, "apply-started", "apply_started"), (2, "applied", "applied")]


def test_terminal_attempt_gap_replays_started_then_terminal_across_restarts(
    harness: Harness, cluster: FakeCluster
) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    assert harness.apply_poll(cluster).outcome == "applied"
    writes = len(cluster.writes())
    state = harness.state_store.load()
    record = state.plans["plan-0008"]
    harness.state_store.save(state.with_record("plan-0008", replace(record, reported=False)))
    recovered_hub = type(harness.hub)(
        plan=harness.hub.plan,
        report_errors=[
            HubProtocolError("Hub report request returned 409", code="report_attempt_gap")
        ],
    )
    harness.hub = recovered_hub

    gap = harness.apply_poll(cluster)
    started = harness.apply_poll(cluster)
    terminal = harness.apply_poll(cluster)

    assert [(result.outcome, result.reported) for result in (gap, started, terminal)] == [
        ("applied", False),
        ("applied", False),
        ("applied", True),
    ]
    assert [report.attempt for report in recovered_hub.attempted] == [2, 1, 2]
    assert _outcomes(harness) == [
        (1, "apply-started", "apply_started"),
        (2, "applied", "applied"),
    ]
    assert harness.state_store.load().plans["plan-0008"].pending_reports == ()
    assert len(cluster.writes()) == writes


def test_terminal_gap_replays_retryable_started_and_terminal_prefix(
    harness: Harness, cluster: FakeCluster
) -> None:
    plan = harness.release_plan("1.0.0", V1)
    release = harness.store.releases.pop(plan.target_release_digest)
    harness.serve(plan)
    retryable = harness.apply_poll(cluster)
    harness.store.releases[plan.target_release_digest] = release
    applied = harness.apply_poll(cluster)
    state = harness.state_store.load()
    record = state.plans["plan-0008"]
    assert [report.attempt for report in record.report_history] == [1, 2, 3]
    harness.state_store.save(state.with_record("plan-0008", replace(record, reported=False)))
    recovered_hub = type(harness.hub)(
        plan=harness.hub.plan,
        report_errors=[
            HubProtocolError("Hub report request returned 409", code="report_attempt_gap")
        ],
    )
    harness.hub = recovered_hub

    results = [harness.apply_poll(cluster) for _ in range(4)]

    assert (retryable.reason_code, applied.outcome) == ("release_unavailable", "applied")
    assert [(result.outcome, result.reported) for result in results] == [
        ("applied", False),
        ("applied", False),
        ("applied", False),
        ("applied", True),
    ]
    assert [report.attempt for report in recovered_hub.attempted] == [3, 1, 2, 3]
    assert harness.state_store.load().plans["plan-0008"].pending_reports == ()


def test_an_expired_plan_is_not_applied_after_a_late_apply_started(
    harness: Harness, cluster: FakeCluster
) -> None:
    plan = harness.serve(harness.release_plan("1.0.0", V1))
    harness.hub.report_errors.append(HubProtocolError("Hub report request returned 503"))
    harness.apply_poll(cluster)

    late = harness.apply_poll(cluster, now=plan.expires_at + timedelta(seconds=1))

    assert (late.outcome, late.reason_code) == ("rejected", "plan_expired")
    assert cluster.writes() == []
    assert _outcomes(harness)[-1] == (2, "rejected", "plan_expired")
    assert _store(harness).load().journal is None


def test_expired_terminal_conflict_halts_across_restart_and_retains_prepared_journal(
    harness: Harness, cluster: FakeCluster
) -> None:
    plan = harness.serve(harness.release_plan("1.0.0", V1))
    harness.hub.report_errors.extend(
        [
            HubProtocolError("Hub report request returned 503"),
            HubProtocolError("Hub report request returned 409", code="report_conflict"),
        ]
    )
    harness.apply_poll(cluster)

    conflict = harness.apply_poll(cluster, now=plan.expires_at + timedelta(seconds=1))
    attempts = len(harness.hub.attempted)
    restarted = harness.apply_poll(cluster, now=plan.expires_at + timedelta(seconds=2))

    assert (conflict.outcome, conflict.reason_code) == ("halted", "report_conflict")
    assert restarted == conflict
    assert len(harness.hub.attempted) == attempts
    journal = _store(harness).load().journal
    assert journal is not None
    assert (journal.plan_id, journal.phase) == ("plan-0008", "prepared")
    assert cluster.writes() == []


def test_applied_terminal_conflict_halts_across_restart_and_retains_done_journal(
    harness: Harness, cluster: FakeCluster
) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    original_submit = harness.hub.submit_report

    def reject_applied(installation_id: str, plan_id: str, report: PlanReport) -> None:
        if report.outcome == "applied":
            harness.hub.attempted.append(report)
            raise HubProtocolError("Hub report request returned 409", code="report_conflict")
        original_submit(installation_id, plan_id, report)

    harness.hub.submit_report = reject_applied  # type: ignore[method-assign]

    conflict = harness.apply_poll(cluster)
    writes = len(cluster.writes())
    attempts = len(harness.hub.attempted)
    restarted = harness.apply_poll(cluster)

    assert (conflict.outcome, conflict.reason_code) == ("halted", "report_conflict")
    assert restarted == conflict
    assert (len(cluster.writes()), len(harness.hub.attempted)) == (writes, attempts)
    journal = _store(harness).load().journal
    assert journal is not None
    assert (journal.plan_id, journal.phase) == ("plan-0008", "done")
    assert harness.hub.states == []


class _Crash(BaseException):
    """Stands in for the agent process dying."""


def _crash_mid_apply(harness: Harness, cluster: FakeCluster) -> None:
    """Poll until the first cluster write, then die, leaving an ``applying`` journal."""

    class CrashAfterFirstWrite:
        def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
            cluster.apply(manifest, dry_run=dry_run)
            if not dry_run:
                raise _Crash

        def get(self, kind: str, name: str) -> Manifest | None:
            return cluster.get(kind, name)

        def delete(self, kind: str, name: str) -> None:
            cluster.delete(kind, name)

    with pytest.raises(_Crash):
        harness.apply_poll(CrashAfterFirstWrite())


def test_an_interrupted_apply_is_rolled_back_and_never_applied_again(
    harness: Harness, cluster: FakeCluster
) -> None:
    _upgrade_to_v2(harness, cluster)
    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))

    _crash_mid_apply(harness, cluster)
    assert cluster.image() == f"{harness.repository}@{V3}"
    assert _store(harness).load().journal.phase == "applying"  # type: ignore[union-attr]

    cluster.calls.clear()
    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    # Only the recorded v2 objects are applied again; v3 is never retried.
    assert cluster.calls == [
        ("apply", "Deployment", "core-control-plane"),
        ("apply", "Service", "core-control-plane"),
    ]
    assert cluster.image() == f"{harness.repository}@{V2}"
    assert _outcomes(harness) == [
        (1, "apply-started", "apply_started"),
        (2, "rolled-back", "apply_failed"),
    ]


def test_a_rollback_that_failed_before_a_restart_is_not_retried(
    harness: Harness, cluster: FakeCluster
) -> None:
    _upgrade_to_v2(harness, cluster)
    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))
    _crash_mid_apply(harness, cluster)
    _store(harness).halt("plan-0010")
    cluster.calls.clear()

    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code) == ("rolled-back", "apply_failed")
    assert json.loads(harness.hub.reports[-1][2].summary)["rollback"] == "failed"
    assert cluster.calls == []
    assert harness.apply_poll(cluster).outcome == "halted"


def test_a_failed_state_report_is_resent_without_another_plan_report(
    harness: Harness, cluster: FakeCluster
) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    harness.hub.state_errors.append(HubProtocolError("Hub state request returned 503"))

    first = harness.apply_poll(cluster)

    assert (first.outcome, first.reported) == ("applied", False)
    assert harness.hub.states == []

    second = harness.apply_poll(cluster)

    assert (second.outcome, second.reported) == ("applied", True)
    assert len(harness.hub.reports) == 2
    assert [state["digest"] for state in harness.hub.states] == [
        load_current_state(harness.state_file).digest
    ]
    assert _store(harness).load().journal is None


def test_a_stale_state_report_is_not_resent(harness: Harness, cluster: FakeCluster) -> None:
    harness.serve(harness.release_plan("1.0.0", V1))
    harness.hub.state_errors.append(HubProtocolError("stale", code="stale_state"))

    result = harness.apply_poll(cluster)

    assert result.reported is True
    assert _store(harness).load().journal is None


def test_a_live_object_without_a_healthy_record_rejects_the_plan(
    harness: Harness, cluster: FakeCluster
) -> None:
    for manifest in render(
        harness.namespace, {("core", "core-control-plane"): f"{harness.repository}@{V1}"}
    ):
        cluster.apply(manifest)
    cluster.calls.clear()
    harness.serve(harness.release_plan("1.0.0", V1))

    result = harness.apply_poll(cluster)

    assert (result.outcome, result.reason_code) == ("rejected", "rollback_target_unknown")
    assert cluster.writes() == []
    assert _outcomes(harness) == [(1, "rejected", "rollback_target_unknown")]


def test_manual_deployment_change_is_reported_and_reconciled_by_drift_reconciliation_plan(
    harness: Harness, cluster: FakeCluster
) -> None:
    _upgrade_to_v2(harness, cluster)
    assert cluster.image() == f"{harness.repository}@{V2}"

    # Simulate a manual out-of-band Deployment change in the cluster.
    manual_image = _image("manual-drift")
    live = cluster.get("Deployment", "core-control-plane")
    assert live is not None
    live["spec"]["template"]["spec"]["containers"][0]["image"] = (
        f"{harness.repository}@{manual_image}"
    )
    cluster.apply(live)
    assert cluster.image() == f"{harness.repository}@{manual_image}"

    # Polling while no Plan is pending detects the live Deployment drift and reports it to the Hub.
    harness.hub.plan = None
    no_plan = harness.apply_poll(cluster)
    assert no_plan.outcome == "no-plan"
    assert len(harness.hub.states) == 1
    drifted_state = load_current_state(harness.state_file)
    assert drifted_state.entities["core"].release_id == "1.1.0"
    assert drifted_state.entities["core"].artifact_digests == frozenset({manual_image})
    assert drifted_state.entities["core"].health == Health.DEGRADED
    assert V2 in (drifted_state.available_artifact_digests or frozenset())

    # When the Hub issues a drift-reconciliation Plan for 1.1.0 in the next matching window,
    # the agent admits and applies it, restoring the Deployment to the signed V2 image.
    reconcile_plan = harness.release_plan(
        "1.1.0", V2, sequence=10, plan_type="drift-reconciliation"
    )
    harness.serve(reconcile_plan)
    reconciled = harness.apply_poll(cluster)
    assert (reconciled.outcome, reconciled.reason_code, reconciled.reported) == (
        "applied",
        "applied",
        True,
    )
    assert cluster.image() == f"{harness.repository}@{V2}"
    restored_state = load_current_state(harness.state_file)
    assert restored_state.entities["core"].release_id == "1.1.0"
    assert restored_state.entities["core"].artifact_digests == frozenset({V2})
    assert restored_state.entities["core"].health == Health.HEALTHY


def test_automatic_apply_requires_bound_authorization_receipt_and_waits_for_earlier_phase(
    harness: Harness, cluster: FakeCluster
) -> None:
    plan = harness.serve(harness.release_plan("1.0.0", V1))

    # 1. Workload phase waits while the earlier infrastructure phase completion receipt is absent.
    infra_receipts: dict[str, LifecyclePhaseCompletionReceipt] = {}
    waiting = harness.apply_poll(
        cluster,
        require_infrastructure_receipt=True,
        read_infrastructure_receipt=lambda plan_id: infra_receipts.get(plan_id),
    )
    assert (waiting.outcome, waiting.reason_code) == (
        "rejected",
        "earlier_phase_receipt_missing",
    )
    assert cluster.writes() == []

    # 2. Recording the infrastructure phase completion receipt for the exact Plan digest unblocks
    # the workload phase on the next poll, unless the local authorization receipt is mismatched.
    infra_receipt = issue_lifecycle_authorization_receipt(
        plan,
        phase="infrastructure",
        window_starts_at=plan.expires_at - timedelta(minutes=30),
        window_ends_at=plan.expires_at,
        issued_at=plan.expires_at - timedelta(minutes=30),
    )
    infra_receipts[plan.plan_id] = LifecyclePhaseCompletionReceipt(
        plan_id=plan.plan_id,
        exact_plan_digest=exact_plan_digest_for(plan),
        fencing_generation=plan.fencing_generation,
        phase="infrastructure",
        authorization_receipt_digest=infra_receipt.digest,
        completed_at=plan.expires_at - timedelta(minutes=25),
    )

    # Mismatched authorization receipt (wrong exact_plan_digest) is refused before cluster writes.
    mismatched = harness.apply_poll(
        cluster,
        require_infrastructure_receipt=True,
        read_infrastructure_receipt=lambda plan_id: infra_receipts.get(plan_id),
        build_authorization_receipt=lambda p, now, prereq: replace(
            issue_lifecycle_authorization_receipt(
                p,
                phase="workload",
                window_starts_at=now,
                window_ends_at=p.expires_at,
                issued_at=now,
                prerequisite_receipt=prereq,
            ),
            exact_plan_digest="sha256:" + "0" * 64,
        ),
    )
    assert (mismatched.outcome, mismatched.reason_code) == (
        "rejected",
        "authorization_receipt_plan_mismatch",
    )
    assert cluster.writes() == []

    # 3. With a valid local authorization receipt bound to the exact Plan digest and earlier phase
    # receipt, the workload phase applies automatically.
    next_plan = harness.serve(harness.release_plan("1.0.0", V1, sequence=9))
    next_infra_receipt = issue_lifecycle_authorization_receipt(
        next_plan,
        phase="infrastructure",
        window_starts_at=next_plan.expires_at - timedelta(minutes=30),
        window_ends_at=next_plan.expires_at,
        issued_at=next_plan.expires_at - timedelta(minutes=30),
    )
    infra_receipts[next_plan.plan_id] = LifecyclePhaseCompletionReceipt(
        plan_id=next_plan.plan_id,
        exact_plan_digest=exact_plan_digest_for(next_plan),
        fencing_generation=next_plan.fencing_generation,
        phase="infrastructure",
        authorization_receipt_digest=next_infra_receipt.digest,
        completed_at=next_plan.expires_at - timedelta(minutes=25),
    )
    applied = harness.apply_poll(
        cluster,
        require_infrastructure_receipt=True,
        read_infrastructure_receipt=lambda plan_id: infra_receipts.get(plan_id),
    )
    assert (applied.outcome, applied.reason_code, applied.reported) == (
        "applied",
        "applied",
        True,
    )
    assert cluster.image() == f"{harness.repository}@{V1}"
