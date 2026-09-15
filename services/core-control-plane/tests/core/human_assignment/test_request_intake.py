from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.assignment_transport import (
    AssignmentIntakeProjection,
    AssignmentRequestNotice,
    assignment_content_digest,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _record(*, operation="assignments.create", roles=None):
    request = {
        "family": "iam",
        "operation": operation,
        "principal_id": "human:owner",
        "idempotency_key": "assignment:example",
        "payload": {
            "principal": {"oid": "human:owner", "roles": ["Owner"] if roles is None else roles},
            "justification": "Private handover prose must stay in its source record.",
            **({"case_id": "operator-" + "1" * 32} if operation != "assignments.create" else {}),
        },
    }
    digest = assignment_content_digest(request)
    record = {
        **request,
        "kind": "operator.proposal",
        "mode": "shadow",
        "proposal_id": f"operator-{digest[:32]}",
        "request_digest": digest,
        "accepted_at": NOW.isoformat(),
    }
    notice = AssignmentRequestNotice(
        proposal_ref="operator-proposal:iam:" + hashlib.sha256(b"assignment:example").hexdigest(),
        proposal_id=record["proposal_id"],
        case_id=(
            record["proposal_id"]
            if operation == "assignments.create"
            else request["payload"]["case_id"]
        ),
        proposal_digest=digest,
        operation=operation,
        accepted_at=NOW,
    )
    return record, notice


async def _intake(*, operation="assignments.create", roles=None):
    receipts = InMemoryStateStore()
    state = InMemoryStateStore()
    record, notice = _record(operation=operation, roles=roles)
    await receipts.write_state(notice.proposal_ref, record)
    return AssignmentRequestIntake(receipts=receipts, store=state), receipts, state, record, notice


@pytest.mark.parametrize(
    "operation", ["assignments.create", "assignments.submit", "assignments.review"]
)
async def test_exact_receipt_produces_only_inert_review_intake(operation):
    intake, _receipts, state, _record_value, notice = await _intake(operation=operation)
    result = await intake.receive(notice, at=NOW)
    assert result.status == "awaiting_agent_review"
    assert result.execution_authority is False
    assert result.approval_authority is False
    assert not await state.read_states("human_assignment:case:", limit=5)
    assert len(tuple(state.audit_entries)) == 1


async def test_replay_and_concurrent_delivery_preserve_one_receipt_and_audit():
    intake, _receipts, state, _record_value, notice = await _intake()
    results = await asyncio.gather(*(intake.receive(notice, at=NOW) for _ in range(10)))
    assert all(item == results[0] for item in results)
    assert len(tuple(state.audit_entries)) == 1
    restarted = AssignmentRequestIntake(receipts=intake.receipts, store=state)
    assert await restarted.receive(notice, at=NOW + timedelta(hours=1)) == results[0]


@pytest.mark.parametrize("field", ["operation", "accepted_at", "proposal_ref"])
async def test_same_proposal_with_changed_notice_cannot_replay(field):
    intake, _receipts, _state, _record_value, notice = await _intake()
    await intake.receive(notice, at=NOW)
    replacement = {
        "operation": "assignments.review",
        "accepted_at": NOW + timedelta(seconds=1),
        "proposal_ref": "operator-proposal:iam:" + "f" * 64,
    }[field]
    changed = AssignmentRequestNotice.model_validate({**notice.model_dump(), field: replacement})
    with pytest.raises(ValueError, match="conflicts"):
        await intake.receive(changed, at=NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("family", "operations"),
        ("principal_id", "other"),
        ("mode", "enforce"),
        ("request_digest", "f" * 64),
    ],
)
async def test_tampered_source_is_held(field, value):
    intake, receipts, _state, record, notice = await _intake()
    await receipts.write_state(notice.proposal_ref, {**record, field: value})
    result = await intake.receive(notice, at=NOW)
    assert result.status == "held"
    assert result.reason == "operator_receipt_mismatch"


@pytest.mark.parametrize(
    "roles", [[], ["Reader"], ["BreakGlass"], ["Owner", {}], ["Administrator"]]
)
async def test_unverified_role_shape_cannot_become_review_authority(roles):
    intake, _receipts, _state, _record_value, notice = await _intake(roles=roles)
    result = await intake.receive(notice, at=NOW)
    assert result.reason == "operator_receipt_unauthorized"


@pytest.mark.parametrize("age", [timedelta(minutes=5), timedelta(seconds=-31)])
async def test_expired_or_future_receipt_is_held(age):
    intake, _receipts, _state, _record_value, notice = await _intake()
    assert (await intake.receive(notice, at=NOW + age)).reason == "operator_receipt_expired"


async def test_missing_source_does_not_poison_later_ordered_delivery():
    record, notice = _record()
    receipts = InMemoryStateStore()
    state = InMemoryStateStore()
    intake = AssignmentRequestIntake(receipts=receipts, store=state)
    assert (await intake.receive(notice, at=NOW)).reason == "operator_receipt_unavailable"
    await receipts.write_state(notice.proposal_ref, record)
    assert (await intake.receive(notice, at=NOW)).status == "awaiting_agent_review"


async def test_store_error_propagates_without_success(monkeypatch):
    intake, receipts, state, _record_value, notice = await _intake()

    async def unavailable(_key):
        raise OSError("test source unavailable")

    monkeypatch.setattr(receipts, "read_state", unavailable)
    with pytest.raises(OSError):
        await intake.receive(notice, at=NOW)
    assert not tuple(state.audit_entries)


def test_notice_and_projection_never_include_private_prose_or_claim_authority():
    record, notice = _record()
    encoded = notice.model_dump_json()
    assert record["payload"]["justification"] not in encoded
    assert "human:owner" not in encoded
    with pytest.raises(ValidationError):
        AssignmentIntakeProjection(
            proposal_id=notice.proposal_id,
            proposal_digest=notice.proposal_digest,
            status="active",
            reason="verified_operator_receipt",
            observed_at=NOW,
        )


@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_transport_authority_requires_literal_false(value):
    _record_value, notice = _record()
    payload = deepcopy(notice.model_dump())
    payload["execution_authority"] = value
    with pytest.raises(ValidationError):
        AssignmentRequestNotice.model_validate(payload)


@pytest.mark.parametrize("value", [0, 1700000000, NOW.replace(tzinfo=None), "2026-09-14"])
def test_notice_rejects_implicit_or_naive_time(value):
    _record_value, notice = _record()
    with pytest.raises(ValidationError):
        AssignmentRequestNotice.model_validate({**notice.model_dump(), "accepted_at": value})
