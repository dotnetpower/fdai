"""Matching ownership is a shadow action proposal, never fresh human approval."""

from __future__ import annotations

import asyncio

import pytest
from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader
from fdai.core.human_assignment.model import AssignmentState
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_runtime_chain import LiveInMemoryEventBus
from tests.core.human_assignment.test_access_apply import _ownership_merged
from tests.core.human_assignment.test_request_processor import NOW, _processor


class ActionBus(LiveInMemoryEventBus):
    def __init__(self):
        super().__init__()
        self.action = asyncio.Event()

    async def publish(self, topic, key, payload):
        receipt = await super().publish(topic, key, payload)
        if topic == "object.action-run":
            self.action.set()
        return receipt


async def test_exact_merge_request_reaches_thor_as_shadow_hil_not_execution():
    processor = _processor()
    merged = await _ownership_merged(processor.cases)
    bus = ActionBus()
    runtime = PantheonRuntime.build(
        provider=bus,
        raw_event_topic="assignment.iam.raw",
        assignment_workflow=AssignmentWorkflowBindings(
            processor.validate,
            processor.validate_review,
            processor,
            clock=lambda: NOW,
            iam_reader=AssignmentIamRequestReader(processor.cases).read,
        ),
    )
    task = asyncio.create_task(runtime.run())
    try:
        await runtime.ingest_raw_event(
            {
                "idempotency_key": "assignment-iam-example",
                "correlation_id": merged.case_id,
                "event_type": "human.assignment.iam_apply_requested",
                "resource_ref": f"human-assignment:{merged.case_id}",
                "payload": {
                    "case_id": merged.case_id,
                    "expected_revision": merged.revision,
                    "ownership_digest": merged.effect_receipts[0].digest,
                    "ownership_ref": merged.effect_receipts[0].receipt_ref,
                },
            }
        )
        await asyncio.wait_for(bus.action.wait(), timeout=3)
        verdict = bus._records["object.verdict"][0][1]
        assert verdict["risk_verdict"] == "hil"
        assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
        assert verdict["execution_authority"] is False
        assert not any(
            item[1]["state"] == "executing" for item in bus._records["object.action-run"]
        )
        current = await processor.cases.get_case(merged.case_id)
        assert current.state is AssignmentState.OWNERSHIP_MERGED
    finally:
        await runtime.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", 1),
        ("expected_revision", True),
        ("ownership_digest", "wrong"),
        ("ownership_ref", "other"),
    ],
)
async def test_iam_request_cannot_borrow_another_ownership_receipt(field, value):
    cases = AssignmentCaseService(InMemoryStateStore())
    merged = await _ownership_merged(cases)
    notice = {
        "case_id": merged.case_id,
        "expected_revision": merged.revision,
        "ownership_digest": merged.effect_receipts[0].digest,
        "ownership_ref": merged.effect_receipts[0].receipt_ref,
    }
    with pytest.raises(ValueError):
        await AssignmentIamRequestReader(cases).read({**notice, field: value})
