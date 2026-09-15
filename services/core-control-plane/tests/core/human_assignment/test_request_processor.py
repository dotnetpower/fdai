from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.assignment_transport import (
    AssignmentRequestNotice,
    assignment_content_digest,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _processor():
    state, source = InMemoryStateStore(), InMemoryStateStore()
    return AssignmentRequestProcessor(
        intake=AssignmentRequestIntake(receipts=source, store=state),
        cases=AssignmentCaseService(state),
    )


async def _notice(processor, operation, *, actor="human:owner", key=None, **payload):
    key = key or f"{operation}:{actor}"
    request = {
        "family": "iam",
        "operation": operation,
        "principal_id": actor,
        "idempotency_key": key,
        "payload": {"principal": {"oid": actor, "roles": ["Owner"]}, **payload},
    }
    digest = assignment_content_digest(request)
    proposal_id = f"operator-{digest[:32]}"
    reference = "operator-proposal:iam:" + hashlib.sha256(key.encode()).hexdigest()
    record = {
        **request,
        "kind": "operator.proposal",
        "mode": "shadow",
        "proposal_id": proposal_id,
        "request_digest": digest,
        "accepted_at": NOW.isoformat(),
    }
    await processor.intake.receipts.write_state(reference, record)
    return AssignmentRequestNotice(
        proposal_ref=reference,
        proposal_id=proposal_id,
        proposal_digest=digest,
        case_id=proposal_id if operation == "assignments.create" else payload["case_id"],
        operation=operation,
        accepted_at=NOW,
    )


async def _create(processor, role="Contributor"):
    notice = await _notice(
        processor,
        "assignments.create",
        idempotency_key="case:example",
        subject_provider="entra",
        subject_id="human:subject",
        requested_role=role,
        duty_bindings=[{"agent_name": "Thor", "duty": "backup", "scope_ref": "scope:platform"}],
        goal_refs=["goal:example"],
        justification="Example assignment request.",
    )
    result = await processor.apply(notice, at=NOW)
    return notice, result


async def _pending(processor, role="Contributor"):
    creation, _result = await _create(processor, role)
    submission = await _notice(
        processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
    )
    await processor.apply(submission, at=NOW)
    return creation


async def test_create_submit_review_materializes_core_without_provider_effects():
    processor = _processor()
    creation = await _pending(processor)
    review = await _notice(
        processor,
        "assignments.review",
        actor="human:reviewer",
        case_id=creation.case_id,
        expected_revision=2,
        decision="approve",
    )
    await processor.validate(review, at=NOW)
    await processor.validate_review(review, at=NOW)
    result = await processor.apply(review, at=NOW)
    assert result["state"] == "approved"
    case = await processor.cases.get_case(result["case_id"])
    assert not case.effect_receipts
    assert len(case.command_receipts) == 3
    assert case.case_id != creation.case_id


@pytest.mark.parametrize("actor", ["human:owner", " HUMAN:OWNER ", "human:subject"])
async def test_requester_and_subject_cannot_review_even_with_owner_role(actor):
    processor = _processor()
    creation = await _pending(processor)
    review = await _notice(
        processor,
        "assignments.review",
        actor=actor,
        case_id=creation.case_id,
        expected_revision=2,
        decision="approve",
    )
    with pytest.raises(ValueError, match="MUST NOT review"):
        await processor.validate_review(review, at=NOW)


async def test_elevated_role_requires_two_distinct_review_commands():
    processor = _processor()
    creation = await _pending(processor, "Owner")
    results = []
    for index in range(2):
        notice = await _notice(
            processor,
            "assignments.review",
            actor=f"human:reviewer-{index}",
            case_id=creation.case_id,
            expected_revision=2 + index,
            decision="approve",
        )
        results.append(await processor.apply(notice, at=NOW))
    assert [item["state"] for item in results] == ["pending_review", "approved"]


async def test_rejection_is_terminal_for_a_different_reviewer():
    processor = _processor()
    creation = await _pending(processor)
    for decision, actor in [("reject", "human:first"), ("approve", "human:second")]:
        notice = await _notice(
            processor,
            "assignments.review",
            actor=actor,
            case_id=creation.case_id,
            expected_revision=2 if decision == "reject" else 3,
            decision=decision,
        )
        if decision == "reject":
            assert (await processor.apply(notice, at=NOW))["state"] == "rejected"
        else:
            with pytest.raises(ValueError, match="pending case"):
                await processor.apply(notice, at=NOW)


async def test_stale_command_does_not_gain_replay_from_an_equal_review_timestamp():
    processor = _processor()
    creation = await _pending(processor)
    arguments = {"actor": "human:reviewer", "case_id": creation.case_id, "decision": "approve"}
    review = await _notice(processor, "assignments.review", expected_revision=2, **arguments)
    await processor.apply(review, at=NOW)
    changed = await _notice(
        processor, "assignments.review", key="different-key", expected_revision=1, **arguments
    )
    with pytest.raises(ValueError, match="stale"):
        await processor.apply(changed, at=NOW)


@pytest.mark.parametrize(
    "operation", ["assignments.create", "assignments.submit", "assignments.review"]
)
async def test_restart_after_case_commit_recovers_exact_command_result(monkeypatch, operation):
    processor = _processor()
    state = processor.cases.store
    if operation == "assignments.create":
        original = state.write_state_with_audit_if_absent
        armed = True

        async def fail_once(key, value, audit_entry):
            nonlocal armed
            if armed and key.startswith("human_assignment:operator-case:"):
                armed = False
                raise OSError("test stopped after case commit")
            return await original(key, value, audit_entry)

        monkeypatch.setattr(state, "write_state_with_audit_if_absent", fail_once)
        with pytest.raises(OSError):
            await _create(processor)
        _notice_value, result = await _create(processor)
        assert result["state"] == "draft"
        return
    creation, _ = await _create(processor)
    if operation == "assignments.review":
        submission = await _notice(
            processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
        )
        await processor.apply(submission, at=NOW)
    notice = await _notice(
        processor,
        operation,
        case_id=creation.case_id,
        expected_revision=1 if operation == "assignments.submit" else 2,
        actor="human:owner" if operation == "assignments.submit" else "human:reviewer",
        **({"decision": "approve"} if operation == "assignments.review" else {}),
    )
    original = state.write_state_with_audit_if_absent
    armed = True

    async def fail_result_once(key, value, audit_entry):
        nonlocal armed
        if armed and key.startswith("human_assignment:command-result:"):
            armed = False
            raise OSError("test stopped before result")
        return await original(key, value, audit_entry)

    monkeypatch.setattr(state, "write_state_with_audit_if_absent", fail_result_once)
    with pytest.raises(OSError):
        await processor.apply(notice, at=NOW)
    restarted = AssignmentRequestProcessor(intake=processor.intake, cases=processor.cases)
    result = await restarted.apply(notice, at=NOW)
    assert result["revision"] == (2 if operation == "assignments.submit" else 3)
    assert await restarted.apply(notice, at=NOW) == result


async def test_concurrent_different_reviews_cannot_share_one_revision():
    processor = _processor()
    creation = await _pending(processor, "Owner")
    notices = [
        await _notice(
            processor,
            "assignments.review",
            actor=f"human:reviewer-{index}",
            case_id=creation.case_id,
            expected_revision=2,
            decision="approve",
        )
        for index in range(2)
    ]
    results = await asyncio.gather(
        *(processor.apply(notice, at=NOW) for notice in notices), return_exceptions=True
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1


async def test_exact_cached_result_does_not_refresh_expired_authorization():
    processor = _processor()
    notice, _result = await _create(processor)
    with pytest.raises(PermissionError, match="expired"):
        await processor.apply(notice, at=NOW + timedelta(minutes=5))


async def test_core_reference_cannot_redirect_a_command_to_another_creation():
    processor = _processor()
    creation, result = await _create(processor)
    await processor.cases.store.write_state(
        f"human_assignment:operator-case:{creation.case_id}",
        {"case_id": result["case_id"], "request_digest": "f" * 64},
    )
    submission = await _notice(
        processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
    )
    with pytest.raises(ValueError, match="identity"):
        await processor.apply(submission, at=NOW)
