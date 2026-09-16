from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.human_reporting import (
    ReportingLineRequestProcessor,
    ReportingLineService,
    StateStoreReportingLineDraftReader,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts import (
    ReportingLineCandidate,
    ReportingLineDirectoryComparison,
    ReportingLineDraftArtifact,
    ReportingLineDraftOutcome,
    ReportingLineExtractionSource,
    ReportingLinePerson,
    ReportingLineSourceSpan,
    reporting_line_candidate_id,
)
from fdai_service_contracts.assignment_transport import (
    AssignmentRequestNotice,
    assignment_content_digest,
)

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


def _artifact() -> ReportingLineDraftArtifact:
    subject = ReportingLinePerson(display_name="Alex Kim", oid="person-a")
    manager = ReportingLinePerson(display_name="Morgan Lee", oid="person-b")
    citation = ReportingLineSourceSpan(
        unit_id="row-2",
        locator="xlsx/sheet:1/row:2",
        quote="Alex Kim | Morgan Lee",
    )
    candidate = ReportingLineCandidate(
        candidate_id=reporting_line_candidate_id(
            subject=subject,
            manager=manager,
            relationship_kind="primary_manager",
            effective_from=None,
            effective_until=None,
            citations=(citation,),
        ),
        subject=subject,
        manager=manager,
        confidence=1.0,
        extraction_source=ReportingLineExtractionSource.DETERMINISTIC,
        citations=(citation,),
        directory_manager_oid="person-b",
        directory_comparison=ReportingLineDirectoryComparison.MATCHED,
    )
    return ReportingLineDraftArtifact(
        upload_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        source_sha256="a" * 64,
        outcome=ReportingLineDraftOutcome.DRAFTED,
        candidates=(candidate,),
    )


def _processor():
    state = InMemoryStateStore()
    source = InMemoryStateStore()
    intake = AssignmentRequestIntake(receipts=source, store=state)
    reporting = ReportingLineRequestProcessor(
        intake=intake,
        cases=ReportingLineService(state),
        drafts=StateStoreReportingLineDraftReader(state),
    )
    return (
        AssignmentRequestProcessor(
            intake=intake,
            cases=AssignmentCaseService(state),
            reporting=reporting,
        ),
        state,
    )


async def _notice(
    processor: AssignmentRequestProcessor,
    operation: str,
    *,
    actor: str,
    roles: list[str],
    key: str,
    **payload: object,
) -> AssignmentRequestNotice:
    request = {
        "family": "iam",
        "operation": operation,
        "principal_id": actor,
        "idempotency_key": key,
        "payload": {
            "principal": {"oid": actor, "roles": roles},
            "case_kind": "report_line",
            **payload,
        },
    }
    digest = assignment_content_digest(request)
    proposal_id = f"operator-{digest[:32]}"
    reference = "operator-proposal:iam:" + hashlib.sha256(key.encode()).hexdigest()
    await processor.intake.receipts.write_state(
        reference,
        {
            **request,
            "kind": "operator.proposal",
            "mode": "shadow",
            "proposal_id": proposal_id,
            "request_digest": digest,
            "accepted_at": NOW.isoformat(),
        },
    )
    return AssignmentRequestNotice(
        schema_version="1.3.0",
        proposal_ref=reference,
        proposal_id=proposal_id,
        proposal_digest=digest,
        case_id=proposal_id if operation == "assignments.create" else str(payload["case_id"]),
        operation=operation,
        accepted_at=NOW,
    )


async def test_fixed_agent_transport_materializes_confirmed_and_reviewed_edge() -> None:
    processor, state = _processor()
    artifact = _artifact()
    await state.write_state(f"report_line_draft:{artifact.upload_id}", artifact.to_dict())
    candidate = artifact.candidates[0]
    create = await _notice(
        processor,
        "assignments.create",
        actor="uploader",
        roles=["Contributor"],
        key="report-line-create",
        idempotency_key="report-line-create",
        upload_id=str(artifact.upload_id),
        candidate_id=candidate.candidate_id,
        effective_from=None,
        effective_until=None,
        supersedes_case_id=None,
    )
    created = await processor.apply(create, at=NOW)
    assert created["schema_version"] == "1.3.0"
    assert created["state"] == "pending_confirmation"

    case = await processor.reporting.cases.get_case(str(created["case_id"]))  # type: ignore[union-attr]
    confirm = await _notice(
        processor,
        "assignments.confirm",
        actor="person-a",
        roles=["Reader"],
        key="report-line-confirm",
        case_id=create.case_id,
        expected_revision=case.revision,
        decision="confirm",
        edge_digest=case.edge_digest,
    )
    confirmed = await processor.apply(confirm, at=NOW)
    assert confirmed["state"] == "pending_owner_review"

    case = await processor.reporting.cases.get_case(str(created["case_id"]))  # type: ignore[union-attr]
    endpoint_review = await _notice(
        processor,
        "assignments.review",
        actor="person-b",
        roles=["Owner"],
        key="report-line-endpoint-review",
        case_id=create.case_id,
        expected_revision=case.revision,
        decision="approve",
        edge_digest=case.edge_digest,
    )
    with pytest.raises(PermissionError, match="independent"):
        await processor.validate_review(endpoint_review, at=NOW)

    review = await _notice(
        processor,
        "assignments.review",
        actor="owner",
        roles=["Owner"],
        key="report-line-review",
        case_id=create.case_id,
        expected_revision=case.revision,
        decision="approve",
        edge_digest=case.edge_digest,
    )
    await processor.validate_review(review, at=NOW)
    reviewed = await processor.apply(review, at=NOW)
    assert reviewed["state"] == "active"
    assert reviewed["execution_authority"] is False


async def test_non_endpoint_confirmation_is_held() -> None:
    processor, state = _processor()
    artifact = _artifact()
    await state.write_state(f"report_line_draft:{artifact.upload_id}", artifact.to_dict())
    create = await _notice(
        processor,
        "assignments.create",
        actor="uploader",
        roles=["Contributor"],
        key="report-line-create",
        idempotency_key="report-line-create",
        upload_id=str(artifact.upload_id),
        candidate_id=artifact.candidates[0].candidate_id,
        effective_from=None,
        effective_until=None,
        supersedes_case_id=None,
    )
    created = await processor.apply(create, at=NOW)
    case = await processor.reporting.cases.get_case(str(created["case_id"]))  # type: ignore[union-attr]
    confirm = await _notice(
        processor,
        "assignments.confirm",
        actor="unrelated",
        roles=["Owner"],
        key="report-line-confirm-unrelated",
        case_id=create.case_id,
        expected_revision=case.revision,
        decision="confirm",
        edge_digest=case.edge_digest,
    )

    with pytest.raises(PermissionError, match="endpoint"):
        await processor.validate(confirm, at=NOW)
