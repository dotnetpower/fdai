"""Readiness is a bounded observation, not deployment or IAM authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.human_assignment import AssignmentReconciler
from fdai.core.human_assignment.readiness import HandoverReadinessPublisher
from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover_readiness import HANDOVER_READINESS_KEY
from tests.core.human_assignment.test_goals import _NOW, _assignment


async def test_empty_readiness_is_not_zero_latency_or_operational_success():
    report = await HandoverReadinessPublisher(InMemoryStateStore(), clock=lambda: _NOW).publish()
    assert report.cases_observed == report.knowledge_observed == 0
    assert report.mean_effect_interval_seconds is None
    assert report.convergence_samples == 0
    assert not report.operationally_ready
    assert not report.execution_authority
    assert report.source_gaps == () and report.external_blockers


async def test_implemented_executor_sources_do_not_remove_external_authority_gates():
    report = await HandoverReadinessPublisher(InMemoryStateStore(), clock=lambda: _NOW).publish()
    assert report.source_gaps == ()
    assert "current_target_bound_executor_authorization" in report.external_blockers
    assert "nonproduction_membership_rollback_drills" in report.external_blockers
    assert not set(report.source_gaps).intersection(report.external_blockers)
    assert "reader_backup_group_acl_proof" not in report.source_gaps
    assert "verified_urgency_forecast_producer" not in report.source_gaps
    assert "document_acl_deletion_performance_cohort" in report.external_blockers
    assert not report.operationally_ready


async def test_valid_effect_intervals_are_measured_without_customer_values():
    store = InMemoryStateStore()
    case = _assignment()
    effects = tuple(
        replace(receipt, received_at=_NOW + timedelta(seconds=30 * index))
        for index, receipt in enumerate(case.effect_receipts)
    )
    await store.write_state(
        "human_assignment:case:example", replace(case, effect_receipts=effects).to_dict()
    )
    report = await HandoverReadinessPublisher(
        store, clock=lambda: _NOW + timedelta(minutes=1)
    ).publish()
    assert report.cases_by_state == {"active": 1}
    assert report.mean_effect_interval_seconds == 30
    assert "subject-1" not in report.model_dump_json()
    assert "case-1" not in report.model_dump_json()


async def test_invalid_case_does_not_hide_other_observations():
    store = InMemoryStateStore()
    await store.write_state("human_assignment:case:valid", _assignment().to_dict())
    await store.write_state("human_assignment:case:invalid", {"revision": True})
    report = await HandoverReadinessPublisher(store, clock=lambda: _NOW).publish()
    assert report.cases_invalid == 1
    assert report.cases_by_state == {"active": 1}
    assert "invalid_lifecycle_evidence" in report.alerts


async def test_partial_page_is_never_claimed_as_a_complete_count():
    store = InMemoryStateStore()
    for index in range(3):
        await store.write_state(f"human_assignment:case:{index}", _assignment().to_dict())
    report = await HandoverReadinessPublisher(store, sample_limit=2, clock=lambda: _NOW).publish()
    assert report.partial
    assert (report.cases_observed, report.cases_total) == (2, 3)
    assert "partial_lifecycle_scan" in report.alerts


async def test_disabled_preference_only_lowers_eligibility():
    report = await HandoverReadinessPublisher(
        InMemoryStateStore(), enabled=False, clock=lambda: _NOW
    ).publish()
    assert not report.enabled and not report.execution_authority
    assert report.mode == "shadow"
    assert "human_access_disabled" in report.alerts


async def test_overdue_degraded_and_knowledge_hold_have_distinct_alerts():
    store = InMemoryStateStore()
    case = _assignment()
    await store.write_state(
        "human_assignment:case:held",
        replace(
            case,
            state=type(case.state).DEGRADED,
            degraded_reason="pending_recovery",
        ).to_dict(),
    )
    await store.write_state(
        "human_assignment:case:applying",
        replace(
            case,
            state=type(case.state).IAM_APPLYING,
            effect_receipts=case.effect_receipts[:1],
        ).to_dict(),
    )
    report = await HandoverReadinessPublisher(
        store, clock=lambda: _NOW + timedelta(hours=2)
    ).publish()
    assert "assignment_recovery_required" in report.alerts
    assert "convergence_overdue" in report.alerts


async def test_future_effect_is_invalid_and_cannot_supply_a_latency_sample():
    store = InMemoryStateStore()
    await store.write_state("human_assignment:case:future", _assignment().to_dict())
    report = await HandoverReadinessPublisher(
        store, clock=lambda: _NOW - timedelta(days=1)
    ).publish()
    assert report.cases_invalid == 1
    assert report.mean_effect_interval_seconds is None


async def test_readiness_clock_rollback_does_not_overwrite_current_report():
    store = InMemoryStateStore()
    first = await HandoverReadinessPublisher(store, clock=lambda: _NOW).publish()
    with pytest.raises(ValueError, match="backwards"):
        await HandoverReadinessPublisher(store, clock=lambda: _NOW - timedelta(seconds=1)).publish()
    assert (await store.read_state(HANDOVER_READINESS_KEY))["revision"] == first.revision


async def test_concurrent_reports_use_cas_and_remain_audited_after_restart():
    store = InMemoryStateStore()
    await asyncio.gather(
        *(HandoverReadinessPublisher(store, clock=lambda: _NOW).publish() for _ in range(2))
    )
    restarted = await HandoverReadinessPublisher(store, clock=lambda: _NOW).publish()
    assert restarted.revision == 3
    assert len(store.audit_entries) == 3


async def test_report_audit_failure_is_not_reported_as_success(monkeypatch):
    store = InMemoryStateStore()

    async def fail(*args, **kwargs):
        raise OSError("synthetic audit unavailable")

    monkeypatch.setattr(store, "write_state_with_audit_if_absent", fail)
    with pytest.raises(OSError):
        await HandoverReadinessPublisher(store, clock=lambda: _NOW).publish()
    assert await store.read_state(HANDOVER_READINESS_KEY) is None


async def test_existing_reconciliation_tick_materializes_the_readiness_without_provider():
    store = InMemoryStateStore()
    worker = AssignmentReconciliationWorker(
        AssignmentReconciler(store=store),
        readiness=HandoverReadinessPublisher(store, clock=lambda: _NOW),
    )
    assert await worker.run_once() == 0
    assert (await store.read_state(HANDOVER_READINESS_KEY))["operationally_ready"] is False


async def test_old_positive_knowledge_disposition_is_stale_not_current_admission():
    from fdai_service_contracts.handover_knowledge import (
        HandoverKnowledgeDecision,
        notice_for_source,
    )
    from tests.core.human_assignment.test_knowledge_source import goal_record

    store = InMemoryStateStore()
    notice = notice_for_source(goal_record(), source="operator", at=_NOW)
    decision = HandoverKnowledgeDecision(
        notice=notice,
        disposition="admitted",
        reason="source_admitted",
        evidence_refs=("doc:example:v1",),
        evidence_digests=("a" * 64,),
    )
    await store.write_state(
        "human_assignment:knowledge:Mimir:old",
        {
            "revision": 1,
            "decision": decision.model_dump(mode="json"),
        },
    )
    report = await HandoverReadinessPublisher(
        store, clock=lambda: _NOW + timedelta(minutes=5)
    ).publish()
    assert report.knowledge_by_disposition == {"stale": 1}
    assert "knowledge_review_required" in report.alerts
