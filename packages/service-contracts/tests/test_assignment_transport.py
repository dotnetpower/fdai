"""First-version assignment wire contracts reject authority and compatibility downgrades."""

from __future__ import annotations

from typing import Literal

import pytest
from fdai_service_contracts.assignment_transport import (
    AssignmentAgentDecision,
    AssignmentCaseResult,
    AssignmentRequestNotice,
    AssignmentRevocationRequest,
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


@pytest.mark.parametrize("version", ["0.9.0", "1.3.0", "2.0.0", 1, None])
def test_unsupported_notice_versions_fail_closed(version):
    with pytest.raises(ValueError):
        AssignmentRequestNotice.model_validate({**_notice(), "schema_version": version})


def test_notice_roundtrips_without_identity_prose_or_unknown_fields():
    notice = AssignmentRequestNotice.model_validate(_notice())
    assert AssignmentRequestNotice.model_validate_json(notice.model_dump_json()) == notice
    with pytest.raises(ValueError):
        AssignmentRequestNotice.model_validate({**_notice(), "principal": "human:owner"})


def test_scoped_v12_notice_is_refused_by_personal_only_v11_reader():
    class PersonalNotice(AssignmentRequestNotice):
        schema_version: Literal["1.0.0", "1.1.0"] = "1.0.0"

    scoped = {**_notice(), "schema_version": "1.2.0"}
    assert AssignmentRequestNotice.model_validate(scoped).schema_version == "1.2.0"
    with pytest.raises(ValueError):
        PersonalNotice.model_validate(scoped)


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


def test_v11_support_keeps_v1_reads_but_legacy_consumers_refuse_v11():
    class LegacyNotice(AssignmentRequestNotice):
        schema_version: Literal["1.0.0"] = "1.0.0"

    assert AssignmentRequestNotice.model_validate(_notice()).schema_version == "1.0.0"
    current = AssignmentRequestNotice.model_validate({**_notice(), "schema_version": "1.1.0"})
    with pytest.raises(ValueError):
        LegacyNotice.model_validate_json(current.model_dump_json())


@pytest.mark.parametrize("value", [True, "7", 0, -1, 7.5])
def test_revocation_wire_pins_reject_coerced_revisions(value):
    with pytest.raises(ValueError):
        AssignmentRevocationRequest.model_validate(
            {"case_id": "old", "revision": 7, "replacement_revisions": {"primary": value}}
        )


@pytest.mark.parametrize("state", ["iam_revoked", "revoked"])
def test_revocation_result_requires_explicit_version_and_effects(state):
    record = {
        "proposal_id": _notice()["proposal_id"],
        "operator_case_id": _notice()["case_id"],
        "request_digest": "b" * 64,
        "case_id": "00000000-0000-0000-0000-000000000001",
        "state": state,
        "revision": 7,
        "ownership_effect_ref": "receipt:ownership",
        "iam_effect_ref": "receipt:iam",
    }
    with pytest.raises(ValueError, match="1.1.0"):
        AssignmentCaseResult.model_validate(record)
    assert AssignmentCaseResult.model_validate({**record, "schema_version": "1.1.0"}).state == state
    with pytest.raises(ValueError, match="effect"):
        AssignmentCaseResult.model_validate(
            {**record, "schema_version": "1.1.0", "iam_effect_ref": None}
        )
