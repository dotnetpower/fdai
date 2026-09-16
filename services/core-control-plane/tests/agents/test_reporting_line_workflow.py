"""Fixed-agent workflow for report-line confirmation and independent review."""

from __future__ import annotations

import asyncio

from fdai_core_service.assignment_intake_consumer import assignment_raw_event

from tests.agents.test_assignment_workflow import SignalingBus, _runtime, _stop
from tests.core.human_reporting.test_request_processor import (
    NOW,
    _artifact,
    _notice,
    _processor,
)


async def test_report_line_confirmation_and_review_both_pass_through_var() -> None:
    processor, state = _processor()
    bus = SignalingBus()
    runtime = _runtime(processor, bus, clock=lambda: NOW)
    task = asyncio.create_task(runtime.run())
    try:
        artifact = _artifact()
        await state.write_state(
            f"report_line_draft:{artifact.upload_id}",
            artifact.to_dict(),
        )
        candidate = artifact.candidates[0]
        creation = await _notice(
            processor,
            "assignments.create",
            actor="uploader",
            roles=["Contributor"],
            key="report-line-agent-create",
            idempotency_key="report-line-agent-create",
            upload_id=str(artifact.upload_id),
            candidate_id=candidate.candidate_id,
            effective_from=None,
            effective_until=None,
            supersedes_case_id=None,
        )
        await runtime.ingest_raw_event(assignment_raw_event(creation))
        created = await bus.outcome(creation)
        assert created["result"] is not None, created
        core_case_id = created["result"]["case_id"]

        case = await processor.reporting.cases.get_case(core_case_id)  # type: ignore[union-attr]
        confirmation = await _notice(
            processor,
            "assignments.confirm",
            actor="person-a",
            roles=["Reader"],
            key="report-line-agent-confirm",
            case_id=creation.case_id,
            expected_revision=case.revision,
            decision="confirm",
            edge_digest=case.edge_digest,
        )
        await runtime.ingest_raw_event(assignment_raw_event(confirmation))
        confirmed = await bus.outcome(confirmation)
        assert confirmed["result"]["state"] == "pending_owner_review"
        confirmation_approvals = [
            item
            for item in bus._records.get("object.approval", [])
            if item[1]["assignment"]["notice"]["proposal_id"] == confirmation.proposal_id
        ]
        assert confirmation_approvals
        assert confirmation_approvals[-1][1]["producer_principal"] == "Var"
        assert (
            confirmation_approvals[-1][1]["assignment"]["reason"] == "human_confirmation_verified"
        )

        case = await processor.reporting.cases.get_case(core_case_id)  # type: ignore[union-attr]
        review = await _notice(
            processor,
            "assignments.review",
            actor="owner",
            roles=["Owner"],
            key="report-line-agent-review",
            case_id=creation.case_id,
            expected_revision=case.revision,
            decision="approve",
            edge_digest=case.edge_digest,
        )
        await runtime.ingest_raw_event(assignment_raw_event(review))
        reviewed = await bus.outcome(review)
        assert reviewed["result"] is not None, reviewed
        assert reviewed["result"]["state"] == "active"
        assert not bus._records.get("object.action-run")
    finally:
        await _stop(runtime, task)
