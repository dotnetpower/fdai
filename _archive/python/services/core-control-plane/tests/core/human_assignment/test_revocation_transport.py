"""Removal intent must never travel as a grant-compatible legacy command."""

from __future__ import annotations

import pytest
from fdai_service_contracts.assignment_transport import AssignmentRequestNotice
from tests.core.human_assignment.test_request_processor import NOW, _notice, _processor
from tests.core.human_assignment.test_revocation import _intent, _old


async def _removal_notice(processor):
    await processor.cases.store.write_state("human_assignment:case:old", _old().to_dict())
    intent = _intent()
    return await _notice(
        processor,
        "assignments.create",
        idempotency_key=intent.idempotency_key,
        subject_provider=intent.subject.provider,
        subject_id=intent.subject.subject_id,
        requested_role=intent.requested_role.value,
        duty_bindings=[item.to_dict() for item in intent.duty_bindings],
        goal_refs=[],
        justification=intent.justification,
        revocation=intent.revocation.to_dict(),
    )


async def test_legacy_transport_cannot_silently_reinterpret_removal_as_a_grant():
    processor = _processor()
    notice = await _removal_notice(processor)
    assert notice.schema_version == "1.0.0"
    with pytest.raises(ValueError, match="1.1.0"):
        await processor.validate(notice, at=NOW)


def _v11(notice):
    return AssignmentRequestNotice.model_validate(
        {**notice.model_dump(mode="json"), "schema_version": "1.1.0"}
    )


@pytest.mark.parametrize(
    "operation", ["assignments.create", "assignments.submit", "assignments.review"]
)
async def test_removal_commands_and_cached_results_preserve_v11(operation):
    processor = _processor()
    creation = _v11(await _removal_notice(processor))
    notice = creation
    result = await processor.apply(creation, at=NOW)
    if operation != "assignments.create":
        notice = _v11(
            await _notice(
                processor, "assignments.submit", case_id=creation.case_id, expected_revision=1
            )
        )
        result = await processor.apply(notice, at=NOW)
    if operation == "assignments.review":
        notice = _v11(
            await _notice(
                processor,
                "assignments.review",
                actor="human:independent-reviewer",
                case_id=creation.case_id,
                expected_revision=2,
                decision="approve",
            )
        )
        await processor.validate_review(notice, at=NOW)
        result = await processor.apply(notice, at=NOW)
    assert result["schema_version"] == "1.1.0"
    case = await processor.cases.get_case(result["case_id"])
    assert case.intent.revocation is not None
    assert not case.effect_receipts
    assert await processor.apply(notice, at=NOW) == result
    downgraded = AssignmentRequestNotice.model_validate(
        {**notice.model_dump(mode="json"), "schema_version": "1.0.0"}
    )
    with pytest.raises(ValueError, match="1.1.0"):
        await processor.apply(downgraded, at=NOW)
