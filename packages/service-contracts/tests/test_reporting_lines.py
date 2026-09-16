from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

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
from fdai_service_contracts.assignment_transport import AssignmentCaseResult


NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


def _candidate(
    *,
    subject_oid: str | None = "person-a",
    manager_oid: str | None = "person-b",
    comparison: ReportingLineDirectoryComparison = ReportingLineDirectoryComparison.MATCHED,
    directory_manager_oid: str | None = "person-b",
) -> ReportingLineCandidate:
    subject = ReportingLinePerson(display_name="Alex Kim", oid=subject_oid)
    manager = ReportingLinePerson(display_name="Morgan Lee", oid=manager_oid)
    citations = (
        ReportingLineSourceSpan(
            unit_id="table-1-row-2",
            locator="xlsx/sheet:1/row:2",
            quote="Alex Kim | Morgan Lee",
        ),
    )
    return ReportingLineCandidate(
        candidate_id=reporting_line_candidate_id(
            subject=subject,
            manager=manager,
            relationship_kind="primary_manager",
            effective_from=NOW,
            effective_until=NOW + timedelta(days=90),
            citations=citations,
        ),
        subject=subject,
        manager=manager,
        effective_from=NOW,
        effective_until=NOW + timedelta(days=90),
        confidence=1.0,
        extraction_source=ReportingLineExtractionSource.DETERMINISTIC,
        citations=citations,
        directory_manager_oid=directory_manager_oid,
        directory_comparison=comparison,
    )


def test_reporting_line_candidate_binds_identity_window_and_source() -> None:
    candidate = _candidate()

    assert candidate.candidate_id.startswith("report-line-")
    assert candidate.directory_comparison is ReportingLineDirectoryComparison.MATCHED
    assert candidate.subject.oid == "person-a"


def test_reporting_line_candidate_rejects_self_reporting() -> None:
    with pytest.raises(ValueError, match="cannot report to themselves"):
        _candidate(manager_oid="PERSON-A", directory_manager_oid="PERSON-A")


def test_reporting_line_candidate_rejects_forged_identity() -> None:
    candidate = _candidate()

    with pytest.raises(ValueError, match="identity does not match"):
        ReportingLineCandidate.model_validate(
            {**candidate.model_dump(mode="json"), "candidate_id": "report-line-" + "0" * 32}
        )


def test_reporting_line_comparison_requires_consistent_directory_evidence() -> None:
    with pytest.raises(ValueError, match="same exact manager"):
        _candidate(directory_manager_oid="person-c")

    conflict = _candidate(
        comparison=ReportingLineDirectoryComparison.CONFLICT,
        directory_manager_oid="person-c",
    )
    assert conflict.directory_comparison is ReportingLineDirectoryComparison.CONFLICT


def test_reporting_line_draft_requires_candidates_for_drafted_outcome() -> None:
    with pytest.raises(ValueError, match="outcome"):
        ReportingLineDraftArtifact(
            upload_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            source_sha256="0" * 64,
            outcome=ReportingLineDraftOutcome.DRAFTED,
        )


def test_reporting_line_draft_rejects_duplicate_candidate_ids() -> None:
    candidate = _candidate()

    with pytest.raises(ValueError, match="candidate ids MUST be unique"):
        ReportingLineDraftArtifact(
            upload_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            source_sha256="0" * 64,
            outcome=ReportingLineDraftOutcome.DRAFTED,
            candidates=(candidate,),
            abstained=(candidate,),
        )


def test_reporting_line_active_result_requires_no_ownership_or_iam_effect() -> None:
    result = AssignmentCaseResult(
        schema_version="1.3.0",
        proposal_id="operator-" + "a" * 32,
        request_digest="a" * 64,
        operator_case_id="operator-" + "b" * 32,
        case_id=str(uuid4()),
        state="active",
        revision=3,
    )

    assert result.ownership_effect_ref is None
    assert result.iam_effect_ref is None
