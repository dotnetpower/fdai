"""HTTP authorization and projection tests for report-line drafts."""

from __future__ import annotations

from uuid import uuid4

from fdai_ingestion_api_service.auth import Authenticator, GroupMapping
from fdai_ingestion_api_service.http import build_app
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
from starlette.testclient import TestClient


class Service:
    capabilities = type("Capabilities", (), {"model_copy": lambda self, update: self})()

    async def get_upload(self, *, actor_id, actor_groups, upload_id):
        del actor_id, actor_groups
        assert upload_id == UPLOAD_ID
        return object()


class Deletion:
    pass


class Drafts:
    async def get(self, upload_id):
        assert upload_id == UPLOAD_ID
        return ARTIFACT


UPLOAD_ID = uuid4()
DOCUMENT_ID = uuid4()
VERSION_ID = uuid4()
SUBJECT = ReportingLinePerson(display_name="Alex Kim", oid="person-a")
MANAGER = ReportingLinePerson(display_name="Morgan Lee", oid="person-b")
CITATION = ReportingLineSourceSpan(
    unit_id="row-2",
    locator="xlsx/sheet:1/row:2",
    quote="Alex Kim | Morgan Lee",
)
CANDIDATE = ReportingLineCandidate(
    candidate_id=reporting_line_candidate_id(
        subject=SUBJECT,
        manager=MANAGER,
        relationship_kind="primary_manager",
        effective_from=None,
        effective_until=None,
        citations=(CITATION,),
    ),
    subject=SUBJECT,
    manager=MANAGER,
    confidence=1.0,
    extraction_source=ReportingLineExtractionSource.DETERMINISTIC,
    citations=(CITATION,),
    directory_manager_oid="person-b",
    directory_comparison=ReportingLineDirectoryComparison.MATCHED,
)
ARTIFACT = ReportingLineDraftArtifact(
    upload_id=UPLOAD_ID,
    document_id=DOCUMENT_ID,
    version_id=VERSION_ID,
    source_sha256="a" * 64,
    outcome=ReportingLineDraftOutcome.DRAFTED,
    candidates=(CANDIDATE,),
)


def test_reader_can_fetch_only_the_authorized_upload_report_line_draft() -> None:
    app = build_app(
        authenticator=Authenticator(
            verifier=lambda _token: {"oid": "reader", "roles": ["Reader"]},
            mapping=GroupMapping("r", "c", "a", "o", "b"),
        ),
        service=Service(),  # type: ignore[arg-type]
        deletion=Deletion(),  # type: ignore[arg-type]
        report_line_drafts=Drafts(),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/ingestion/uploads/{UPLOAD_ID}/report-line-draft",
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 200
    assert response.json()["candidates"][0]["candidate_id"] == CANDIDATE.candidate_id
    assert response.json()["candidates"][0]["subject"]["oid"] == "person-a"


def test_unbound_report_line_draft_route_fails_closed() -> None:
    app = build_app(
        authenticator=Authenticator(
            verifier=lambda _token: {"oid": "reader", "roles": ["Reader"]},
            mapping=GroupMapping("r", "c", "a", "o", "b"),
        ),
        service=Service(),  # type: ignore[arg-type]
        deletion=Deletion(),  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.get(f"/ingestion/uploads/{UPLOAD_ID}/report-line-draft")

    assert response.status_code == 404
