from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fdai_document_worker_service.report_lines import (
    ExtractedReportingLine,
    ReportLineBootstrapConsumer,
    ReportLineGenerationBudget,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    ProtectionState,
    ReportingLineDirectoryComparison,
    ReportingLineDraftArtifact,
    ReportingLineManagerObservation,
    ReportingLineManagerStatus,
    ReportingLineResolvedIdentity,
    RetentionPolicy,
    SourceStorageMode,
    StructuralUnit,
    UploadSession,
)

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


class Directory:
    def __init__(
        self,
        identities: dict[str, str],
        managers: dict[str, str] | None = None,
    ) -> None:
        self.identities = identities
        self.managers = managers or {}
        self.lookups: list[str] = []

    async def resolve(self, display_name: str) -> ReportingLineResolvedIdentity | None:
        self.lookups.append(display_name)
        oid = self.identities.get(display_name)
        return ReportingLineResolvedIdentity(oid=oid) if oid else None

    async def manager_for(self, subject_oid: str) -> ReportingLineManagerObservation:
        manager = self.managers.get(subject_oid)
        return (
            ReportingLineManagerObservation(
                status=ReportingLineManagerStatus.RESOLVED,
                manager_oid=manager,
                observed_at=NOW,
            )
            if manager
            else ReportingLineManagerObservation(
                status=ReportingLineManagerStatus.UNAVAILABLE,
                observed_at=NOW,
            )
        )


class Store:
    def __init__(self) -> None:
        self.artifact: ReportingLineDraftArtifact | None = None

    async def put(self, artifact: ReportingLineDraftArtifact) -> None:
        self.artifact = artifact


class RecordingInterpreter:
    def __init__(self) -> None:
        self.calls = 0

    async def interpret(self, envelope: DocumentEnvelope) -> tuple[ExtractedReportingLine, ...]:
        del envelope
        self.calls += 1
        return ()


def _session_and_envelope(
    *units: StructuralUnit,
) -> tuple[UploadSession, DocumentEnvelope]:
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="organization-chart.xlsx",
        collection_id="restricted",
        object_key="source",
        media_type_hint=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        expected_size=1,
        expected_sha256="0" * 64,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.REPORT_LINE_BOOTSTRAP,),
        access=AccessDescriptor(
            reference="collection:restricted",
            collection_id="restricted",
        ),
        retention=RetentionPolicy(policy_version="test"),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    envelope = DocumentEnvelope(
        document_id=document_id,
        version_id=version_id,
        source_sha256="a" * 64,
        media_type=session.media_type_hint,
        observed_format="ooxml",
        size_bytes=1,
        collection_id="restricted",
        purposes=session.purposes,
        protection_state=ProtectionState.NONE,
        access_descriptor_ref=session.access.reference,
        units=units,
        extractor_name="test",
        extractor_version="1",
    )
    return session, envelope


async def test_consumer_extracts_explicit_edge_and_matches_directory_manager() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text="subject: Alex Kim; manager: Morgan Lee",
        )
    )
    store = Store()

    warnings = await ReportLineBootstrapConsumer(
        directory=Directory(
            {"Alex Kim": "person-a", "Morgan Lee": "person-b"},
            {"person-a": "person-b"},
        ),
        store=store,
    ).consume(session=session, envelope=envelope)

    assert warnings == ()
    assert store.artifact is not None
    assert len(store.artifact.candidates) == 1
    candidate = store.artifact.candidates[0]
    assert candidate.subject.oid == "person-a"
    assert candidate.manager.oid == "person-b"
    assert candidate.directory_comparison is ReportingLineDirectoryComparison.MATCHED
    assert candidate.citations[0].locator == "paragraph:1#line:1"


async def test_consumer_does_not_send_deterministic_edges_to_interpreter() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text="subject: Alex Kim; manager: Morgan Lee",
        )
    )
    interpreter = RecordingInterpreter()

    await ReportLineBootstrapConsumer(
        directory=Directory(
            {"Alex Kim": "person-a", "Morgan Lee": "person-b"},
            {"person-a": "person-b"},
        ),
        store=Store(),
        interpreter=interpreter,
    ).consume(session=session, envelope=envelope)

    assert interpreter.calls == 0


async def test_consumer_extracts_docx_table_by_header_and_row() -> None:
    units = (
        StructuralUnit(
            unit_id="header-subject",
            kind="table",
            locator="docx/table:1/row:1/cell:1",
            text="Employee",
            table_cell_role="header",
        ),
        StructuralUnit(
            unit_id="header-manager",
            kind="table",
            locator="docx/table:1/row:1/cell:2",
            text="Manager",
            table_cell_role="header",
        ),
        StructuralUnit(
            unit_id="row-subject",
            kind="table",
            locator="docx/table:1/row:2/cell:1",
            text="Alex Kim",
            table_cell_role="body",
        ),
        StructuralUnit(
            unit_id="row-manager",
            kind="table",
            locator="docx/table:1/row:2/cell:2",
            text="Morgan Lee",
            table_cell_role="body",
        ),
    )
    session, envelope = _session_and_envelope(*units)
    store = Store()

    await ReportLineBootstrapConsumer(
        directory=Directory(
            {"Alex Kim": "person-a", "Morgan Lee": "person-b"},
            {"person-a": "person-b"},
        ),
        store=store,
    ).consume(session=session, envelope=envelope)

    assert store.artifact is not None
    assert store.artifact.candidates[0].citations[0].locator == "docx/table:1/row:2"


async def test_consumer_holds_directory_conflict_for_human_review() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text="직원: Alex Kim; 관리자: Morgan Lee",
        )
    )
    store = Store()

    warnings = await ReportLineBootstrapConsumer(
        directory=Directory(
            {"Alex Kim": "person-a", "Morgan Lee": "person-b"},
            {"person-a": "person-c"},
        ),
        store=store,
    ).consume(session=session, envelope=envelope)

    assert store.artifact is not None
    assert store.artifact.candidates == ()
    assert store.artifact.abstained[0].directory_comparison is (
        ReportingLineDirectoryComparison.CONFLICT
    )
    assert "require human review" in warnings[0]


async def test_consumer_holds_unresolved_people_without_guessing() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text="subject: Alex Kim; manager: Unknown Manager",
        )
    )
    store = Store()

    await ReportLineBootstrapConsumer(
        directory=Directory({"Alex Kim": "person-a"}),
        store=store,
    ).consume(session=session, envelope=envelope)

    assert store.artifact is not None
    assert store.artifact.candidates == ()
    assert [item.display_name for item in store.artifact.unresolved_people] == ["Unknown Manager"]


async def test_consumer_abstains_before_directory_io_when_unit_budget_is_exceeded() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text="subject: Alex Kim; manager: Morgan Lee",
        ),
        StructuralUnit(
            unit_id="line-2",
            kind="paragraph",
            locator="paragraph:2",
            text="subject: Morgan Lee; manager: Taylor Park",
        ),
    )
    directory = Directory({})
    store = Store()

    warnings = await ReportLineBootstrapConsumer(
        directory=directory,
        store=store,
        budget=ReportLineGenerationBudget(max_units=1),
    ).consume(session=session, envelope=envelope)

    assert directory.lookups == []
    assert warnings[0] == "reporting-line source unit budget exceeded"
    assert store.artifact is not None
    assert store.artifact.outcome.value == "abstained"


async def test_consumer_abstains_before_directory_io_when_identity_budget_is_exceeded() -> None:
    session, envelope = _session_and_envelope(
        StructuralUnit(
            unit_id="line-1",
            kind="paragraph",
            locator="paragraph:1",
            text=(
                "subject: Alex Kim; manager: Morgan Lee\nsubject: Taylor Park; manager: Jordan Choi"
            ),
        )
    )
    directory = Directory({})
    store = Store()

    warnings = await ReportLineBootstrapConsumer(
        directory=directory,
        store=store,
        budget=ReportLineGenerationBudget(max_directory_lookups=3),
    ).consume(session=session, envelope=envelope)

    assert directory.lookups == []
    assert warnings[0] == "reporting-line directory lookup budget exceeded"
