"""First-version assignment wire contracts reject authority and compatibility downgrades."""

from __future__ import annotations

import pytest
from fdai_service_contracts.assignment_transport import (
    AssignmentAgentDecision,
    AssignmentCaseResult,
    AssignmentRequestNotice,
)


def _notice():
    return {
        "proposal_ref": "operator-proposal:iam:" + "a" * 64,
        "proposal_id": "operator-" + "b" * 32,
        "case_id": "operator-" + "b" * 32,
        "proposal_digest": "b" * 64,
        "operation": "assignments.create",
        "accepted_at": "2026-09-14T00:00:00Z",
    }


@pytest.mark.parametrize("version", ["0.9.0", "1.1.0", "2.0.0", 1, None])
def test_unsupported_notice_versions_fail_closed(version):
    with pytest.raises(ValueError):
        AssignmentRequestNotice.model_validate({**_notice(), "schema_version": version})


def test_notice_roundtrips_without_identity_prose_or_unknown_fields():
    notice = AssignmentRequestNotice.model_validate(_notice())
    assert AssignmentRequestNotice.model_validate_json(notice.model_dump_json()) == notice
    with pytest.raises(ValueError):
        AssignmentRequestNotice.model_validate({**_notice(), "principal": "human:owner"})


@pytest.mark.parametrize("revision", [True, "3", 0, -1, 1.5])
def test_case_result_never_coerces_revision_authority(revision):
    with pytest.raises(ValueError):
        AssignmentCaseResult.model_validate(
            {
                "proposal_id": _notice()["proposal_id"],
                "operator_case_id": _notice()["case_id"],
                "request_digest": "b" * 64,
                "case_id": "00000000-0000-0000-0000-000000000001",
                "state": "approved",
                "revision": revision,
            }
        )


def test_review_disposition_requires_an_actual_review_request():
    with pytest.raises(ValueError):
        AssignmentAgentDecision.model_validate(
            {
                "notice": _notice(),
                "disposition": "reviewed",
                "reason": "independent_review_verified",
            }
        )


@pytest.mark.parametrize(
    "reason", ["command_validated", "case_materialized", "independent_review_verified"]
)
def test_held_disposition_cannot_carry_a_success_reason(reason):
    with pytest.raises(ValueError):
        AssignmentAgentDecision.model_validate(
            {"notice": _notice(), "disposition": "held", "reason": reason}
        )
