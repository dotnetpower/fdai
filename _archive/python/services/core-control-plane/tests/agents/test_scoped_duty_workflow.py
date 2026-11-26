"""Real fixed-agent subscribers carry ownership-only scoped requests without ActionRun."""

from __future__ import annotations

import asyncio

from fdai_core_service.assignment_intake_consumer import assignment_raw_event
from fdai_core_service.assignment_outcome_consumer import AssignmentOutcomeConsumer

from tests.agents.test_assignment_workflow import SignalingBus, _runtime, _stop
from tests.core.human_assignment.test_scoped_duty_cases import AT, FIRST, SECOND
from tests.core.human_assignment.test_scoped_duty_cases import runtime as runtime
from tests.core.human_assignment.test_scoped_duty_ownership import delivery
from tests.core.human_assignment.test_scoped_duty_requests import creation, notice, review_notice
from tests.core.human_assignment.test_scoped_duty_requests import processor as processor


async def test_actual_subscribers_deliver_scoped_two_owner_review_to_one_draft(processor, runtime):
    bus = SignalingBus()
    pantheon = _runtime(processor, bus, clock=lambda: AT)
    ownership = delivery(runtime)
    consumer = AssignmentOutcomeConsumer(processor.cases.store, clock=lambda: AT, scoped=ownership)
    task = asyncio.create_task(pantheon.run())
    try:
        first = await creation(processor)
        await pantheon.ingest_raw_event(assignment_raw_event(first))
        assert (await bus.outcome(first))["result"]["state"] == "draft"
        submitted = await notice(
            processor, "assignments.submit", case_id=first.case_id, expected_revision=1
        )
        await pantheon.ingest_raw_event(assignment_raw_event(submitted))
        result = (await bus.outcome(submitted))["result"]
        for actor in (FIRST, SECOND):
            reviewed = await review_notice(processor, first, result, actor=actor)
            await pantheon.ingest_raw_event(assignment_raw_event(reviewed))
            result = (await bus.outcome(reviewed))["result"]
            await consumer.deliver(bus.outcomes[reviewed.proposal_id], bus=bus)
        assert result["schema_version"] == "1.2.0" and result["state"] == "approved"
        await consumer.deliver(bus.outcomes[reviewed.proposal_id], bus=bus)
        assert len(ownership.publisher.records) == 1
        assert not bus._records.get("object.action-run")
        assert not any(topic.endswith(".dlq") for topic in bus._records)
        materialized = await processor.scoped.cases.get(result["case_id"])
        assert materialized.state == "ownership_pr_open"
        assert not await processor.cases.store.read_states("human_assignment:case:", limit=10)
        serialized = str([item for values in bus._records.values() for item in values])
        assert "Review explicit operational duty coverage" not in serialized
        assert "human:primary" not in serialized
        assert "human:reviewer-one" not in serialized
    finally:
        await _stop(pantheon, task)


async def test_unbound_scoped_provider_is_an_audited_hold_not_iam(processor):
    from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor

    bus = SignalingBus()
    missing = AssignmentRequestProcessor(processor.intake, processor.cases)
    pantheon = _runtime(missing, bus, clock=lambda: AT)
    task = asyncio.create_task(pantheon.run())
    try:
        first = await creation(processor)
        await pantheon.ingest_raw_event(assignment_raw_event(first))
        outcome = await bus.outcome(first)
        assert outcome["disposition"] == "held" and outcome["reason"] == "command_held"
        assert not await processor.cases.store.read_states(
            "human_assignment:scoped-case:", limit=10
        )
        assert not bus._records.get("object.action-run")
    finally:
        await _stop(pantheon, task)
