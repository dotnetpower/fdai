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


async def test_scoped_duty_request_processor_validation_and_race_branches(processor, monkeypatch):
    from fdai.core.human_assignment.scoped_duty_requests import revision, text

    with pytest.raises(ValueError, match="nonempty text"):
        text({"k": " padded "}, "k")
    with pytest.raises(ValueError, match="positive integer"):
        revision({"expected_revision": 0})

    scoped = processor.scoped
    first, res = await pending_request(processor)

    # validate_review rejects non-review operation and invalid decision
    with pytest.raises(ValueError, match="requires a review command"):
        await scoped.validate_review(first, at=AT)

    bad_dec = await notice(
        processor,
        "assignments.review",
        actor=FIRST,
        key="bad-dec",
        case_id=first.case_id,
        expected_revision=res["revision"],
        decision="maybe",
        plan_digest="a" * 64,
    )
    with pytest.raises(ValueError, match="review decision is invalid"):
        await scoped.validate_review(bad_dec, at=AT)

    # validate rejects stale revision and non-requester submit
    stale_sub = await notice(
        processor,
        "assignments.submit",
        key="stale-sub",
        case_id=first.case_id,
        expected_revision=99,
    )
    with pytest.raises(ValueError, match="revision is stale"):
        await scoped.validate(stale_sub, at=AT)

    other_sub = await notice(
        processor,
        "assignments.submit",
        actor=FIRST,
        key="other-sub",
        case_id=first.case_id,
        expected_revision=res["revision"],
    )
    with pytest.raises(PermissionError, match="only the scoped requester"):
        await scoped.validate(other_sub, at=AT)

    # case() missing alias or mismatched alias digest
    unconv = await notice(
        processor,
        "assignments.submit",
        key="unconv",
        case_id="operator-" + "9" * 32,
        expected_revision=1,
    )
    with pytest.raises(ValueError, match="has not converged"):
        await scoped.validate(unconv, at=AT)

    other_created = await notice(
        processor,
        "assignments.create",
        key="other-created-case",
        idempotency_key="other-created-case",
        request=request().model_dump(mode="json"),
        justification="Review explicit operational duty coverage.",
    )
    other_res = await scoped.apply(other_created, at=AT)
    alias_key = "human_assignment:operator-case:" + first.case_id
    orig_alias = await processor.cases.store.read_state(alias_key)
    await processor.cases.store.write_state(
        alias_key,
        {**orig_alias, "case_id": other_res["case_id"]},
    )
    with pytest.raises(ValueError, match="does not match its sealed creation"):
        await scoped.validate(other_sub, at=AT)
    await processor.cases.store.write_state(alias_key, orig_alias)

    # apply() alias conflict, result mismatch, and concurrent result race
    c2 = await notice(
        processor,
        "assignments.create",
        key="alias-conflict-scoped",
        idempotency_key="alias-conflict-scoped",
        request=request().model_dump(mode="json"),
        justification="Review explicit operational duty coverage.",
    )
    await processor.cases.store.write_state(
        "human_assignment:operator-case:" + c2.case_id,
        {"case_id": "other", "case_kind": "scoped_duty", "request_digest": "e" * 64},
    )
    with pytest.raises(ValueError, match="creation reference conflicts"):
        await scoped.apply(c2, at=AT)

    res_key = "human_assignment:command-result:" + first.proposal_id
    orig_res = await processor.cases.store.read_state(res_key)
    assert await scoped.apply(first, at=AT) == orig_res
    await processor.cases.store.write_state(res_key, {**orig_res, "revision": 99})
    with pytest.raises(ValueError, match="differs from the original command transition"):
        await scoped.apply(first, at=AT)
    await processor.cases.store.write_state(res_key, orig_res)

    # source() error branches (lines 40, 42, 55)
    from fdai.core.human_assignment.request_intake import AssignmentRequestIntake

    missing_ntc = AssignmentRequestNotice(
        schema_version="1.2.0",
        proposal_ref="operator-proposal:iam:" + "0" * 64,
        proposal_id="operator-" + "0" * 32,
        case_id="operator-" + "0" * 32,
        proposal_digest="0" * 64,
        operation="assignments.create",
        accepted_at=AT,
    )
    with pytest.raises(PermissionError, match="unavailable or changed"):
        await scoped.source(missing_ntc)

    orig_reason = AssignmentRequestIntake.receipt_reason
    monkeypatch.setattr(
        AssignmentRequestIntake,
        "receipt_reason",
        lambda *_a, **_kw: "verified_operator_receipt",
    )
    with pytest.raises(ValueError, match="require transport 1.2.0"):
        await scoped.source(missing_ntc)

    upper_ntc = await notice(
        processor,
        "assignments.create",
        actor="Human:Upper",
        key="upper-actor",
        idempotency_key="upper-actor",
        request=request().model_dump(mode="json"),
        justification="Review explicit operational duty coverage.",
    )
    with pytest.raises(ValueError, match="MUST already be normalized"):
        await scoped.source(upper_ntc)
    monkeypatch.setattr(AssignmentRequestIntake, "receipt_reason", orig_reason)

    # Concurrent result write race
    c3 = await notice(
        processor,
        "assignments.create",
        key="race-result-scoped",
        idempotency_key="race-result-scoped",
        request=request().model_dump(mode="json"),
        justification="Review explicit operational duty coverage.",
    )
    orig_write = processor.cases.store.write_state_with_audit_if_absent

    async def fail_res_write(k, v, a):
        if k == "human_assignment:command-result:" + c3.proposal_id:
            return False
        return await orig_write(k, v, a)

    monkeypatch.setattr(processor.cases.store, "write_state_with_audit_if_absent", fail_res_write)
    with pytest.raises(ValueError, match="conflicts after a concurrent command"):
        await scoped.apply(c3, at=AT)
    monkeypatch.setattr(processor.cases.store, "write_state_with_audit_if_absent", orig_write)
