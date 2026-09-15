"""Actual declared subscriptions carry commands through the fixed-owner agent pipeline."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from fdai.agents import (
    AssignmentWorkflowBindings,
    PantheonRuntime,
    Saga,
    StateStoreAuditChainAdapter,
)
from fdai.core.human_assignment import AssignmentOwnershipCoordinator, VerifiedOwnershipMerge
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.core.stewardship.names import AGENT_NAMES
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.assignment_intake_consumer import assignment_raw_event
from fdai_core_service.assignment_outcome_consumer import AssignmentOutcomeConsumer

from tests.agents.test_runtime_chain import LiveInMemoryEventBus
from tests.core.human_assignment.test_request_processor import NOW, _notice, _processor


class SignalingBus(LiveInMemoryEventBus):
    def __init__(self):
        super().__init__()
        self.outcomes = {}
        self.signals = {}

    async def publish(self, topic, key, payload):
        result = await super().publish(topic, key, payload)
        if topic == "object.audit-entry" and payload.get("kind") == "human_assignment":
            decision = payload["assignment"]
            if decision["disposition"] in {"held", "materialized"}:
                proposal = decision["notice"]["proposal_id"]
                self.outcomes[proposal] = dict(payload)
                self.signals.setdefault(proposal, asyncio.Event()).set()
        return result

    async def outcome(self, notice):
        await asyncio.wait_for(
            self.signals.setdefault(notice.proposal_id, asyncio.Event()).wait(), timeout=3
        )
        return self.outcomes[notice.proposal_id]["assignment"]


def _runtime(processor, bus, *, bindings=True, clock=lambda: NOW, audit_store=None):
    return PantheonRuntime.build(
        provider=bus,
        raw_event_topic="assignment.test.raw",
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(audit_store or processor.cases.store)),
        assignment_workflow=(
            AssignmentWorkflowBindings(
                processor.validate, processor.validate_review, processor, clock=clock
            )
            if bindings
            else None
        ),
    )


async def _create_notice(processor, *, complete_map=False):
    return await _notice(
        processor,
        "assignments.create",
        idempotency_key="case:example",
        subject_provider="entra",
        subject_id="00000000-0000-0000-0000-000000009999",
        requested_role="Contributor",
        duty_bindings=[
            {"agent_name": name, "duty": "backup", "scope_ref": "scope:platform"}
            for name in (AGENT_NAMES if complete_map else ("Thor",))
            if name != "Loki"
        ],
        goal_refs=["goal:example"],
        justification="Example assignment request.",
    )


async def _stop(runtime, task):
    await runtime.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_declared_agent_chain_creates_submits_and_reviews_without_action_run():
    processor, bus = _processor(), SignalingBus()
    runtime = _runtime(processor, bus)
    task = asyncio.create_task(runtime.run())
    try:
        creation = await _create_notice(processor)
        await runtime.ingest_raw_event(assignment_raw_event(creation))
        assert (await bus.outcome(creation))["result"]["state"] == "draft"
        submission = await _notice(
            processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
        )
        await runtime.ingest_raw_event(assignment_raw_event(submission))
        assert (await bus.outcome(submission))["result"]["state"] == "pending_review"
        review = await _notice(
            processor,
            "assignments.review",
            actor="human:reviewer",
            case_id=creation.case_id,
            expected_revision=2,
            decision="approve",
        )
        await runtime.ingest_raw_event(assignment_raw_event(review))
        result = await bus.outcome(review)
        assert result["result"]["state"] == "approved"
        assert result["execution_authority"] is False
        assert bus._records.get("object.approval")
        assert not bus._records.get("object.action-run")
        assert not any(topic.endswith(".dlq") for topic in bus._records)
        serialized = str([item for values in bus._records.values() for item in values])
        assert "Example assignment request" not in serialized
        assert "human:subject" not in serialized
    finally:
        await _stop(runtime, task)


async def test_unbound_assignment_judgment_is_a_visible_audited_hold():
    processor, bus = _processor(), SignalingBus()
    runtime = _runtime(processor, bus, bindings=False)
    task = asyncio.create_task(runtime.run())
    try:
        notice = await _create_notice(processor)
        await runtime.ingest_raw_event(assignment_raw_event(notice))
        assert (await bus.outcome(notice))["reason"] == "agent_binding_unavailable"
        assert not await processor.cases.store.read_states("human_assignment:case:", limit=5)
        assert not bus._records.get("object.action-run")
    finally:
        await _stop(runtime, task)


async def test_fresh_intake_cannot_hide_expiry_before_materialization():
    processor, bus = _processor(), SignalingBus()
    checks = 0

    def clock():
        nonlocal checks
        checks += 1
        return NOW if checks == 1 else NOW + timedelta(minutes=5)

    runtime = _runtime(processor, bus, clock=clock)
    task = asyncio.create_task(runtime.run())
    try:
        notice = await _create_notice(processor)
        await runtime.ingest_raw_event(assignment_raw_event(notice))
        assert (await bus.outcome(notice))["reason"] == "materialization_held"
        assert not await processor.cases.store.read_states("human_assignment:case:", limit=5)
    finally:
        await _stop(runtime, task)


async def test_failed_saga_audit_never_seals_or_materializes(monkeypatch):
    processor, bus = _processor(), SignalingBus()
    audit = InMemoryStateStore()
    attempted = asyncio.Event()

    async def unavailable(_entry):
        attempted.set()
        raise OSError("test audit unavailable")

    monkeypatch.setattr(audit, "append_audit_entry", unavailable)
    runtime = _runtime(processor, bus, audit_store=audit)
    task = asyncio.create_task(runtime.run())
    try:
        notice = await _create_notice(processor)
        await runtime.ingest_raw_event(assignment_raw_event(notice))
        await asyncio.wait_for(attempted.wait(), timeout=3)
        assert not bus._records.get("object.audit-entry")
        assert not await processor.cases.store.read_states("human_assignment:case:", limit=5)
    finally:
        await _stop(runtime, task)


@pytest.mark.parametrize("owner", ["Var", "Muninn"])
async def test_unaudited_owner_decision_cannot_skip_saga(owner):
    processor, bus = _processor(), SignalingBus()
    runtime = _runtime(processor, bus)
    notice = await _create_notice(processor)
    payload = {
        "kind": "human_assignment",
        "producer_principal": "Forseti",
        "correlation_id": notice.case_id,
        "audited_topic": "object.verdict",
        "assignment": {
            "notice": notice.model_dump(mode="json"),
            "disposition": "validated",
            "reason": "command_validated",
        },
    }
    with pytest.raises(ValueError, match="Saga"):
        await runtime.agents[owner].on_typed_message("object.audit-entry", payload)
    assert not await processor.cases.store.read_states("human_assignment:case:", limit=5)


async def test_sealed_case_opens_one_review_pr_and_only_exact_merge_records_effect():
    processor, bus = _processor(), SignalingBus()
    runtime = _runtime(processor, bus)
    publisher = RecordingRemediationPrPublisher()
    coordinator = AssignmentOwnershipCoordinator(
        cases=processor.cases,
        store=processor.cases.store,
        pr_publisher=publisher,
        event_bus=bus,
        event_topic="assignment.test.effects",
    )
    base = load_stewardship_from_yaml(
        Path(__file__).resolve().parents[4] / "config/agent-stewardship.yaml", environ={}
    )
    delivery = AssignmentOutcomeConsumer(
        processor.cases.store, coordinator, base, clock=lambda: NOW
    )
    task = asyncio.create_task(runtime.run())
    try:
        creation = await _create_notice(processor, complete_map=True)
        await runtime.ingest_raw_event(assignment_raw_event(creation))
        await bus.outcome(creation)
        submission = await _notice(
            processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
        )
        await runtime.ingest_raw_event(assignment_raw_event(submission))
        await bus.outcome(submission)
        review = await _notice(
            processor,
            "assignments.review",
            actor="human:reviewer",
            case_id=creation.case_id,
            expected_revision=2,
            decision="approve",
        )
        await runtime.ingest_raw_event(assignment_raw_event(review))
        outcome = await bus.outcome(review)
        sealed = bus.outcomes[review.proposal_id]
        await delivery.deliver(sealed, bus=bus)
        await delivery.deliver(sealed, bus=bus)
        assert len(publisher.records) == 1
        case_id = outcome["result"]["case_id"]
        case = await processor.cases.get_case(case_id)
        assert case.state.value == "ownership_pr_open"
        proposal = await processor.cases.store.read_state(
            f"human_assignment:ownership-proposal:{case_id}"
        )
        with pytest.raises(ValueError, match="does not match"):
            await coordinator.record_verified_merge(
                case_id=case_id,
                expected_revision=case.revision,
                actor_ref="github:example",
                merge=VerifiedOwnershipMerge(proposal["pr_ref"], "a" * 40, "wrong", NOW),
            )
        merged = await coordinator.record_verified_merge(
            case_id=case_id,
            expected_revision=case.revision,
            actor_ref="github:example",
            merge=VerifiedOwnershipMerge(
                proposal["pr_ref"], "a" * 40, publisher.records[0].patch, NOW
            ),
        )
        assert merged.state.value == "ownership_merged"
        assert not merged.has_required_effects
        assert not bus._records.get("object.action-run")
    finally:
        await _stop(runtime, task)


async def test_forged_materialization_without_canonical_result_cannot_open_a_pr():
    processor, bus = _processor(), SignalingBus()
    runtime = _runtime(processor, bus)
    task = asyncio.create_task(runtime.run())
    try:
        notice = await _create_notice(processor)
        await runtime.ingest_raw_event(assignment_raw_event(notice))
        await bus.outcome(notice)
        sealed = bus.outcomes[notice.proposal_id]
        sealed["assignment"]["result"]["state"] = "approved"
        with pytest.raises(ValueError, match="canonical"):
            await AssignmentOutcomeConsumer(processor.cases.store).deliver(sealed, bus=bus)
    finally:
        await _stop(runtime, task)
