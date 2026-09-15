"""Fixed owners review removals; synthetic effect receipts never become live approval."""

from __future__ import annotations

import asyncio

from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment import AssignmentReconciler, EffectKind
from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
from fdai_core_service.assignment_intake_consumer import assignment_raw_event
from fdai_core_service.assignment_outcome_consumer import AssignmentOutcomeConsumer

from tests.agents.test_assignment_iam_request import ActionBus
from tests.agents.test_assignment_workflow import SignalingBus, _runtime, _stop
from tests.core.human_assignment.test_request_processor import NOW, _notice, _processor
from tests.core.human_assignment.test_revocation import _effect, _reviewed
from tests.core.human_assignment.test_revocation_delivery import _base, _coordinator
from tests.core.human_assignment.test_revocation_transport import _removal_notice, _v11


async def test_revocation_reenters_huginn_forseti_thor_without_becoming_a_grant():
    coordinator = await _coordinator()
    approved = await _reviewed(coordinator.cases)
    processor = _processor()
    bus = ActionBus()
    runtime = PantheonRuntime.build(
        provider=bus,
        raw_event_topic="assignment.iam.raw",
        assignment_workflow=AssignmentWorkflowBindings(
            processor.validate,
            processor.validate_review,
            processor,
            clock=lambda: NOW,
            iam_reader=AssignmentIamRequestReader(coordinator.cases).read,
        ),
    )
    task = asyncio.create_task(runtime.run())
    try:
        await coordinator.request_revocation(case_id=approved.case_id, expected_revision=3)
        event = await anext(coordinator.event_bus.subscribe("iam.raw", "input"))
        await runtime.ingest_raw_event(event.payload)
        await asyncio.wait_for(bus.action.wait(), timeout=3)
        verdict = bus._records["object.verdict"][0][1]
        assert verdict["action_type"] == "ops.revoke-human-access"
        assert verdict["risk_verdict"] == "hil"
        assert verdict["params"]["replacement_revisions"] == {"backup": 7, "primary": 7}
        assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
        assert verdict["execution_authority"] is False
        assert not any(row[1]["state"] == "executing" for row in bus._records["object.action-run"])
        assert (await coordinator.cases.get_case("old")).state.value == "active"
    finally:
        await _stop(runtime, task)


async def test_sealed_revocation_waits_for_effect_before_bounded_artifact_recovery():
    coordinator = await _coordinator()
    seed = _processor()
    processor = AssignmentRequestProcessor(
        AssignmentRequestIntake(receipts=seed.intake.receipts, store=coordinator.store),
        coordinator.cases,
    )
    bus = SignalingBus()
    runtime = _runtime(processor, bus)
    delivery = AssignmentOutcomeConsumer(coordinator.store, coordinator, _base(), clock=lambda: NOW)
    task = asyncio.create_task(runtime.run())
    try:
        creation = _v11(await _removal_notice(processor))
        await runtime.ingest_raw_event(assignment_raw_event(creation))
        assert (await bus.outcome(creation))["result"]["schema_version"] == "1.1.0"
        submit = _v11(
            await _notice(
                processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
            )
        )
        await runtime.ingest_raw_event(assignment_raw_event(submit))
        await bus.outcome(submit)
        review = _v11(
            await _notice(
                processor,
                "assignments.review",
                actor="human:reviewer",
                case_id=creation.case_id,
                expected_revision=2,
                decision="approve",
            )
        )
        await runtime.ingest_raw_event(assignment_raw_event(review))
        outcome = await bus.outcome(review)
        assert outcome["result"]["state"] == "approved"
        assert not bus._records.get("object.action-run")
        await delivery.deliver(bus.outcomes[review.proposal_id], bus=bus)
        assert not coordinator.pr_publisher.records
        assert not (await coordinator.cases.get_case("old")).revocation_case_id
        case_id = outcome["result"]["case_id"]
        applying = await coordinator.cases.begin_iam_apply(
            case_id=case_id, expected_revision=3, actor_ref="Thor", now=NOW
        )
        removed = await coordinator.cases.record_effect(
            case_id=case_id,
            expected_revision=applying.revision,
            receipt=_effect(EffectKind.IAM),
            actor_ref="synthetic-independent-observer",
        )
        worker = AssignmentReconciliationWorker(
            AssignmentReconciler(store=coordinator.store),
            removal_artifact=delivery.reconcile_revocation,
        )
        assert await worker.run_once() >= 1
        assert len(coordinator.pr_publisher.records) == 1
        assert (await coordinator.cases.get_case(case_id)).state.value == "ownership_pr_open"
        await worker.run_once()
        assert len(coordinator.pr_publisher.records) == 1
        assert removed.state.value == "iam_revoked"
        assert (await coordinator.cases.get_case("old")).state.value == "degraded"
    finally:
        await _stop(runtime, task)
