from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.core.human_reporting import (
    EndpointDecision,
    OwnerDecision,
    ReportingLineCaseState,
    ReportingLineModelError,
    ReportingLineService,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
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

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


def _candidate(
    subject: str,
    manager: str,
    *,
    comparison: ReportingLineDirectoryComparison = ReportingLineDirectoryComparison.MATCHED,
    directory_manager: str | None = None,
) -> ReportingLineCandidate:
    subject_person = ReportingLinePerson(display_name=subject.title(), oid=subject)
    manager_person = ReportingLinePerson(display_name=manager.title(), oid=manager)
    citation = ReportingLineSourceSpan(
        unit_id=f"{subject}-{manager}",
        locator=f"xlsx/sheet:1/{subject}",
        quote=f"{subject} | {manager}",
    )
    return ReportingLineCandidate(
        candidate_id=reporting_line_candidate_id(
            subject=subject_person,
            manager=manager_person,
            relationship_kind="primary_manager",
            effective_from=None,
            effective_until=None,
            citations=(citation,),
        ),
        subject=subject_person,
        manager=manager_person,
        confidence=1.0,
        extraction_source=ReportingLineExtractionSource.DETERMINISTIC,
        citations=(citation,),
        directory_manager_oid=directory_manager or manager,
        directory_comparison=comparison,
    )


def _artifact(*candidates: ReportingLineCandidate) -> ReportingLineDraftArtifact:
    return ReportingLineDraftArtifact(
        upload_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        source_sha256="a" * 64,
        outcome=ReportingLineDraftOutcome.DRAFTED,
        candidates=candidates,
    )


def _principal(oid: str, *roles: Role) -> Principal:
    return Principal(oid=oid, roles=frozenset(roles))


async def _activate(
    service: ReportingLineService,
    *,
    artifact: ReportingLineDraftArtifact,
    candidate_id: str,
    requester: str = "uploader",
    confirmer: str,
    owner: str,
    supersedes_case_id: str | None = None,
    effective_until: datetime | None = None,
):
    case = await service.create_case(
        principal=_principal(requester, Role.CONTRIBUTOR),
        artifact=artifact,
        candidate_id=candidate_id,
        supersedes_case_id=supersedes_case_id,
        effective_until=effective_until,
        now=NOW,
    )
    case = await service.confirm(
        principal=_principal(confirmer, Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )
    return await service.review(
        principal=_principal(owner, Role.OWNER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=2),
    )


async def test_edge_requires_endpoint_confirmation_and_independent_owner() -> None:
    store = InMemoryStateStore()
    service = ReportingLineService(store)
    candidate = _candidate("person-a", "person-b")
    artifact = _artifact(candidate)

    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=artifact,
        candidate_id=candidate.candidate_id,
        now=NOW,
    )
    assert case.state is ReportingLineCaseState.PENDING_CONFIRMATION

    with pytest.raises(PermissionError, match="endpoint"):
        await service.confirm(
            principal=_principal("other", Role.OWNER),
            case_id=case.case_id,
            expected_revision=case.revision,
            decision=EndpointDecision.CONFIRM,
            edge_digest=case.edge_digest,
            now=NOW,
        )

    confirmed = await service.confirm(
        principal=_principal("person-a", Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )
    assert confirmed.state is ReportingLineCaseState.PENDING_OWNER_REVIEW

    with pytest.raises(PermissionError, match="independent"):
        await service.review(
            principal=_principal("person-a", Role.OWNER),
            case_id=case.case_id,
            expected_revision=confirmed.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=confirmed.edge_digest,
            now=NOW + timedelta(minutes=2),
        )
    with pytest.raises(PermissionError, match="independent"):
        await service.review(
            principal=_principal("person-b", Role.OWNER),
            case_id=case.case_id,
            expected_revision=confirmed.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=confirmed.edge_digest,
            now=NOW + timedelta(minutes=2),
        )

    active = await service.review(
        principal=_principal("owner", Role.OWNER),
        case_id=case.case_id,
        expected_revision=confirmed.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=confirmed.edge_digest,
        now=NOW + timedelta(minutes=2),
    )
    assert active.state is ReportingLineCaseState.ACTIVE
    assert (await service.current_graph(at=NOW + timedelta(minutes=3))).edges[0].manager_ref == (
        "person-b"
    )


async def test_directory_conflict_cannot_be_confirmed() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate(
        "person-a",
        "person-b",
        comparison=ReportingLineDirectoryComparison.CONFLICT,
        directory_manager="person-c",
    )
    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        now=NOW,
    )

    assert case.state is ReportingLineCaseState.CONFLICT
    with pytest.raises(ReportingLineModelError, match="not awaiting confirmation"):
        await service.confirm(
            principal=_principal("person-a", Role.READER),
            case_id=case.case_id,
            expected_revision=case.revision,
            decision=EndpointDecision.CONFIRM,
            edge_digest=case.edge_digest,
            now=NOW,
        )


async def test_explicit_endpoint_rejection_holds_edge() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        now=NOW,
    )

    rejected = await service.confirm(
        principal=_principal("person-b", Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.REJECT,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    assert rejected.state is ReportingLineCaseState.CONFLICT
    assert (await service.current_graph(at=NOW + timedelta(minutes=2))).edges == ()


async def test_other_endpoint_can_reject_after_first_confirmation() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        now=NOW,
    )
    confirmed = await service.confirm(
        principal=_principal("person-a", Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    rejected = await service.confirm(
        principal=_principal("person-b", Role.READER),
        case_id=case.case_id,
        expected_revision=confirmed.revision,
        decision=EndpointDecision.REJECT,
        edge_digest=confirmed.edge_digest,
        now=NOW + timedelta(minutes=2),
    )

    assert rejected.state is ReportingLineCaseState.CONFLICT


async def test_owner_cannot_activate_expired_relationship_evidence() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        effective_until=NOW + timedelta(minutes=2),
        now=NOW,
    )
    confirmed = await service.confirm(
        principal=_principal("person-a", Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ReportingLineModelError, match="expired"):
        await service.review(
            principal=_principal("owner", Role.OWNER),
            case_id=case.case_id,
            expected_revision=confirmed.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=confirmed.edge_digest,
            now=NOW + timedelta(minutes=2),
        )


async def test_replacement_requires_same_subject_and_supersedes_current_edge() -> None:
    service = ReportingLineService(InMemoryStateStore())
    first_candidate = _candidate("person-a", "person-b")
    first = await _activate(
        service,
        artifact=_artifact(first_candidate),
        candidate_id=first_candidate.candidate_id,
        confirmer="person-a",
        owner="owner-1",
    )
    second_candidate = _candidate("person-a", "person-c")
    second = await _activate(
        service,
        artifact=_artifact(second_candidate),
        candidate_id=second_candidate.candidate_id,
        confirmer="person-c",
        owner="owner-2",
        supersedes_case_id=first.case_id,
        effective_until=NOW + timedelta(days=30),
    )

    graph = await service.current_graph(at=NOW + timedelta(minutes=3))

    assert len(graph.edges) == 1
    assert graph.edges[0].case_id == second.case_id
    assert graph.edges[0].manager_ref == "person-c"
    assert (await service.current_graph(at=NOW + timedelta(days=31))).edges == ()


async def test_parallel_active_manager_without_supersession_is_rejected() -> None:
    service = ReportingLineService(InMemoryStateStore())
    first_candidate = _candidate("person-a", "person-b")
    await _activate(
        service,
        artifact=_artifact(first_candidate),
        candidate_id=first_candidate.candidate_id,
        confirmer="person-a",
        owner="owner-1",
    )
    second_candidate = _candidate("person-a", "person-c")
    second_artifact = _artifact(second_candidate)
    second = await service.create_case(
        principal=_principal("uploader-2", Role.CONTRIBUTOR),
        artifact=second_artifact,
        candidate_id=second_candidate.candidate_id,
        now=NOW,
    )
    second = await service.confirm(
        principal=_principal("person-c", Role.READER),
        case_id=second.case_id,
        expected_revision=second.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=second.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ReportingLineModelError, match="multiple active primary managers"):
        await service.review(
            principal=_principal("owner-2", Role.OWNER),
            case_id=second.case_id,
            expected_revision=second.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=second.edge_digest,
            now=NOW + timedelta(minutes=2),
        )


async def test_replacement_cannot_target_an_unreviewed_edge() -> None:
    service = ReportingLineService(InMemoryStateStore())
    first_candidate = _candidate("person-a", "person-b")
    first = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(first_candidate),
        candidate_id=first_candidate.candidate_id,
        now=NOW,
    )
    replacement = _candidate("person-a", "person-c")

    with pytest.raises(ReportingLineModelError, match="active prior edge"):
        await service.create_case(
            principal=_principal("uploader-2", Role.CONTRIBUTOR),
            artifact=_artifact(replacement),
            candidate_id=replacement.candidate_id,
            supersedes_case_id=first.case_id,
            now=NOW,
        )


async def test_cycle_is_rejected_before_second_edge_activates() -> None:
    service = ReportingLineService(InMemoryStateStore())
    first_candidate = _candidate("person-a", "person-b")
    await _activate(
        service,
        artifact=_artifact(first_candidate),
        candidate_id=first_candidate.candidate_id,
        confirmer="person-a",
        owner="owner-1",
    )
    second_candidate = _candidate("person-b", "person-a")
    second = await service.create_case(
        principal=_principal("uploader-2", Role.CONTRIBUTOR),
        artifact=_artifact(second_candidate),
        candidate_id=second_candidate.candidate_id,
        now=NOW,
    )
    second = await service.confirm(
        principal=_principal("person-b", Role.READER),
        case_id=second.case_id,
        expected_revision=second.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=second.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ReportingLineModelError, match="cycle"):
        await service.review(
            principal=_principal("owner-2", Role.OWNER),
            case_id=second.case_id,
            expected_revision=second.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=second.edge_digest,
            now=NOW + timedelta(minutes=2),
        )


async def test_concurrent_reviews_cannot_activate_two_primary_managers() -> None:
    service = ReportingLineService(InMemoryStateStore())
    first_candidate = _candidate("person-a", "person-b")
    second_candidate = _candidate("person-a", "person-c")
    first = await service.create_case(
        principal=_principal("uploader-1", Role.CONTRIBUTOR),
        artifact=_artifact(first_candidate),
        candidate_id=first_candidate.candidate_id,
        now=NOW,
    )
    second = await service.create_case(
        principal=_principal("uploader-2", Role.CONTRIBUTOR),
        artifact=_artifact(second_candidate),
        candidate_id=second_candidate.candidate_id,
        now=NOW,
    )
    first = await service.confirm(
        principal=_principal("person-a", Role.READER),
        case_id=first.case_id,
        expected_revision=first.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=first.edge_digest,
        now=NOW + timedelta(minutes=1),
    )
    second = await service.confirm(
        principal=_principal("person-c", Role.READER),
        case_id=second.case_id,
        expected_revision=second.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=second.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    outcomes = await asyncio.gather(
        service.review(
            principal=_principal("owner-1", Role.OWNER),
            case_id=first.case_id,
            expected_revision=first.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=first.edge_digest,
            now=NOW + timedelta(minutes=2),
        ),
        service.review(
            principal=_principal("owner-2", Role.OWNER),
            case_id=second.case_id,
            expected_revision=second.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=second.edge_digest,
            now=NOW + timedelta(minutes=2),
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(item, ReportingLineModelError) for item in outcomes) == 1
    assert len((await service.current_graph(at=NOW + timedelta(minutes=3))).edges) == 1
