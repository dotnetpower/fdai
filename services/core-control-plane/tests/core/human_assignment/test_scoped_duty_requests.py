"""Existing sealed request transport carries scoped intent without personal IAM authority."""

from __future__ import annotations

import hashlib

import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.scoped_duty_requests import ScopedDutyRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.assignment_transport import (
    AssignmentCaseResult,
    AssignmentRequestNotice,
    assignment_content_digest,
)
from tests.core.human_assignment.test_scoped_duty_cases import (
    AT,
    FIRST,
    REQUESTER,
    SECOND,
    request,
)
from tests.core.human_assignment.test_scoped_duty_cases import runtime as runtime


@pytest.fixture
def processor(runtime):
    cases = runtime[0]
    intake = AssignmentRequestIntake(InMemoryStateStore(), cases.store)
    return AssignmentRequestProcessor(
        intake, AssignmentCaseService(cases.store), ScopedDutyRequestProcessor(intake, cases)
    )


async def notice(processor, operation, *, actor=REQUESTER, key=None, **payload):
    identity = key or operation + ":" + actor
    raw = {
        "family": "iam",
        "operation": operation,
        "principal_id": actor,
        "idempotency_key": identity,
        "payload": {
            "principal": {"oid": actor, "roles": ["Owner"]},
            "case_kind": "scoped_duty",
            **payload,
        },
    }
    digest = assignment_content_digest(raw)
    identifier = "operator-" + digest[:32]
    reference = "operator-proposal:iam:" + hashlib.sha256(identity.encode()).hexdigest()
    record = {
        **raw,
        "kind": "operator.proposal",
        "mode": "shadow",
        "proposal_id": identifier,
        "request_digest": digest,
        "accepted_at": AT.isoformat(),
    }
    await processor.intake.receipts.write_state(reference, record)
    return AssignmentRequestNotice(
        schema_version="1.2.0",
        proposal_ref=reference,
        proposal_id=identifier,
        case_id=identifier if operation == "assignments.create" else payload["case_id"],
        proposal_digest=digest,
        operation=operation,
        accepted_at=AT,
    )


async def creation(processor):
    return await notice(
        processor,
        "assignments.create",
        idempotency_key="example-scoped-case",
        request=request().model_dump(mode="json"),
        justification="Review explicit operational duty coverage.",
    )


async def pending_request(processor):
    first = await creation(processor)
    result = await processor.apply(first, at=AT)
    submission = await notice(
        processor, "assignments.submit", case_id=first.case_id, expected_revision=result["revision"]
    )
    result = await processor.apply(submission, at=AT)
    return first, result


async def review_notice(processor, first, current, *, actor=FIRST):
    case = await processor.scoped.cases.get(current["case_id"])
    return await notice(
        processor,
        "assignments.review",
        actor=actor,
        case_id=first.case_id,
        expected_revision=case.revision,
        decision="approve",
        plan_digest=case.plan()["digest"],
    )


async def test_scoped_commands_use_distinct_namespace_and_no_iam_result(processor):
    first, result = await pending_request(processor)
    for actor in (FIRST, SECOND):
        review = await review_notice(processor, first, result, actor=actor)
        await processor.validate_review(review, at=AT)
        result = await processor.apply(review, at=AT)
    parsed = AssignmentCaseResult.model_validate(result)
    assert parsed.schema_version == "1.2.0" and parsed.state == "approved"
    assert parsed.iam_effect_ref is None and parsed.ownership_effect_ref is None
    assert not await processor.cases.store.read_states("human_assignment:case:", limit=10)


async def test_older_notice_cannot_reinterpret_scoped_intent_as_personal(processor):
    first = await creation(processor)
    for version in ("1.0.0", "1.1.0"):
        old = AssignmentRequestNotice.model_validate(
            {**first.model_dump(), "schema_version": version}
        )
        with pytest.raises(PermissionError):
            await processor.apply(old, at=AT)
    assert not await processor.cases.store.read_states("human_assignment:", limit=10)


async def test_unbound_scoped_processor_cannot_fall_back_to_personal_iam(processor):
    first = await creation(processor)
    unbound = AssignmentRequestProcessor(processor.intake, processor.cases)
    with pytest.raises(ValueError, match="unavailable"):
        await unbound.apply(first, at=AT)


async def test_scoped_input_cannot_smuggle_role_or_revocation(processor):
    for extra in ({"requested_role": "Owner"}, {"revocation": {}}, {"subject_id": "human:other"}):
        first = await notice(
            processor,
            "assignments.create",
            key=str(extra),
            idempotency_key="example-scoped-case",
            request=request().model_dump(mode="json"),
            justification="Review operational coverage.",
            **extra,
        )
        with pytest.raises(ValueError, match="fields"):
            await processor.validate(first, at=AT)


async def test_interrupted_result_replay_retains_original_transition_after_later_review(
    processor, monkeypatch
):
    first, result = await pending_request(processor)
    review = await review_notice(processor, first, result)
    key = "human_assignment:command-result:" + review.proposal_id
    store = processor.cases.store
    original = store.write_state_with_audit_if_absent

    async def fail_result(state_key, value, audit_entry):
        if state_key == key:
            raise OSError("result write interrupted")
        return await original(state_key, value, audit_entry)

    with monkeypatch.context() as patch:
        patch.setattr(store, "write_state_with_audit_if_absent", fail_result)
        with pytest.raises(OSError):
            await processor.apply(review, at=AT)
    later = await review_notice(processor, first, result, actor=SECOND)
    assert (await processor.apply(later, at=AT))["state"] == "approved"
    replay = await processor.apply(review, at=AT)
    assert (replay["state"], replay["revision"]) == ("pending_review", 3)


@pytest.mark.parametrize("state", ["active", "iam_applying", "iam_revoked", "revoked", "degraded"])
def test_scoped_result_cannot_report_personal_iam_states(state):
    with pytest.raises(ValueError):
        AssignmentCaseResult(
            schema_version="1.2.0",
            proposal_id="operator-" + "a" * 32,
            request_digest="a" * 64,
            operator_case_id="operator-" + "a" * 32,
            case_id="00000000-0000-0000-0000-000000000001",
            state=state,
            revision=1,
            ownership_effect_ref="merge:example",
            iam_effect_ref="iam:example",
        )
