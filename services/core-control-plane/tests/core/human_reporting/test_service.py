from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import fdai.core.human_reporting.graph_repository as graph_repository
import fdai.core.human_reporting.service as reporting_service
import pytest
from fdai.core.human_reporting import (
    EndpointConfirmation,
    EndpointDecision,
    OwnerDecision,
    ReportingLineCaseState,
    ReportingLineGraphConflictError,
    ReportingLineModelError,
    ReportingLineService,
)
from fdai.core.human_reporting.graph_repository import GRAPH_KEY
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


class GraphBarrierStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.graph_write_started = asyncio.Event()
        self.release_graph_write = asyncio.Event()

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if key == GRAPH_KEY:
            self.graph_write_started.set()
            await self.release_graph_write.wait()
        return await super().write_state_with_audit_if_absent(key, value, audit_entry)


class ActivationOutcomeRaceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.inject_conflict = False

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if (
            self.inject_conflict
            and audit_entry.get("action_kind") == "human.reporting.activation_completed"
        ):
            self.inject_conflict = False
            conflict = {**value, "state": ReportingLineCaseState.CONFLICT.value}
            applied = await super().compare_and_set_state_with_audit(
                key,
                conflict,
                expected_revision=expected_revision,
                audit_entry={
                    "actor": "test",
                    "action_kind": "human.reporting.concurrent_conflict",
                    "case_id": value["case_id"],
                },
            )
            assert applied
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


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
    at: datetime = NOW,
):
    case = await service.create_case(
        principal=_principal(requester, Role.CONTRIBUTOR),
        artifact=artifact,
        candidate_id=candidate_id,
        supersedes_case_id=supersedes_case_id,
        effective_until=effective_until,
        now=at,
    )
    case = await service.confirm(
        principal=_principal(confirmer, Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=at + timedelta(minutes=1),
    )
    return await service.review(
        principal=_principal(owner, Role.OWNER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=case.edge_digest,
        now=at + timedelta(minutes=2),
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


async def test_exact_endpoint_confirmation_replay_returns_recorded_transition() -> None:
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

    replay = await service.confirm(
        principal=_principal("person-a", Role.READER),
        case_id=case.case_id,
        expected_revision=case.revision,
        decision=EndpointDecision.CONFIRM,
        edge_digest=case.edge_digest,
        now=NOW + timedelta(minutes=1),
    )

    assert replay == confirmed


async def test_case_model_rejects_non_endpoint_confirmation() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    case = await service.create_case(
        principal=_principal("uploader", Role.CONTRIBUTOR),
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        now=NOW,
    )

    with pytest.raises(ReportingLineModelError, match="relationship endpoint"):
        replace(
            case,
            state=ReportingLineCaseState.PENDING_OWNER_REVIEW,
            revision=case.revision + 1,
            confirmation=EndpointConfirmation(
                principal_ref="unrelated-person",
                decision=EndpointDecision.CONFIRM,
                decided_at=NOW + timedelta(minutes=1),
                edge_digest=case.edge_digest,
            ),
        )


async def test_owner_review_freezes_endpoint_decisions_before_graph_activation() -> None:
    store = GraphBarrierStore()
    service = ReportingLineService(store)
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
    review = asyncio.create_task(
        service.review(
            principal=_principal("owner", Role.OWNER),
            case_id=case.case_id,
            expected_revision=confirmed.revision,
            decision=OwnerDecision.APPROVE,
            edge_digest=confirmed.edge_digest,
            now=NOW + timedelta(minutes=2),
        )
    )
    await store.graph_write_started.wait()
    try:
        frozen = await service.get_case(case.case_id)
        assert frozen.state is ReportingLineCaseState.ACTIVATION_PENDING
        with pytest.raises(ReportingLineModelError, match="revision is stale"):
            await service.confirm(
                principal=_principal("person-b", Role.READER),
                case_id=case.case_id,
                expected_revision=confirmed.revision,
                decision=EndpointDecision.REJECT,
                edge_digest=confirmed.edge_digest,
                now=NOW + timedelta(minutes=2),
            )
    finally:
        store.release_graph_write.set()

    active = await review
    assert active.state is ReportingLineCaseState.ACTIVE
    assert (await service.current_graph(at=NOW + timedelta(minutes=3))).edges[0].case_id == (
        active.case_id
    )

    replay = await service.review(
        principal=_principal("owner", Role.OWNER),
        case_id=case.case_id,
        expected_revision=confirmed.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=confirmed.edge_digest,
        now=NOW + timedelta(minutes=2),
    )
    assert replay == active


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


async def test_case_rejects_unbounded_validity_and_future_start() -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    artifact = _artifact(candidate)

    with pytest.raises(ReportingLineModelError, match="validity exceeds"):
        await service.create_case(
            principal=_principal("uploader", Role.CONTRIBUTOR),
            artifact=artifact,
            candidate_id=candidate.candidate_id,
            effective_until=NOW + timedelta(days=367),
            now=NOW,
        )

    with pytest.raises(ReportingLineModelError, match="too far in the future"):
        await service.create_case(
            principal=_principal("uploader", Role.CONTRIBUTOR),
            artifact=artifact,
            candidate_id=candidate.candidate_id,
            effective_from=NOW + timedelta(days=367),
            effective_until=NOW + timedelta(days=368),
            now=NOW,
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
    graph_record = await service.store.read_state(GRAPH_KEY)
    assert graph_record is not None
    assert [item["case_id"] for item in graph_record["cases"]] == [second.case_id]
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
    still_pending = await service.get_case(second.case_id)
    assert still_pending.state is ReportingLineCaseState.PENDING_OWNER_REVIEW
    rejected = await service.review(
        principal=_principal("owner-2", Role.OWNER),
        case_id=second.case_id,
        expected_revision=still_pending.revision,
        decision=OwnerDecision.REJECT,
        edge_digest=still_pending.edge_digest,
        now=NOW + timedelta(minutes=3),
    )
    assert rejected.state is ReportingLineCaseState.REJECTED


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


async def test_activation_race_conflict_exits_frozen_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    async def precheck_succeeds(*_args: object, **_kwargs: object) -> None:
        return None

    async def activation_conflicts(*_args: object, **_kwargs: object) -> None:
        raise ReportingLineGraphConflictError("concurrent graph conflict")

    monkeypatch.setattr(
        reporting_service,
        "validate_reporting_case_activation",
        precheck_succeeds,
    )
    monkeypatch.setattr(
        reporting_service,
        "activate_reporting_case",
        activation_conflicts,
    )

    conflicted = await service.review(
        principal=_principal("owner", Role.OWNER),
        case_id=case.case_id,
        expected_revision=confirmed.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=confirmed.edge_digest,
        now=NOW + timedelta(minutes=2),
    )

    assert conflicted.state is ReportingLineCaseState.CONFLICT
    assert conflicted.owner_review is not None
    assert conflicted.owner_review.decision is OwnerDecision.APPROVE


async def test_case_conflict_after_graph_write_retracts_the_exact_edge() -> None:
    store = ActivationOutcomeRaceStore()
    service = ReportingLineService(store)
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
    store.inject_conflict = True

    conflicted = await service.review(
        principal=_principal("owner", Role.OWNER),
        case_id=case.case_id,
        expected_revision=confirmed.revision,
        decision=OwnerDecision.APPROVE,
        edge_digest=confirmed.edge_digest,
        now=NOW + timedelta(minutes=2),
    )

    assert conflicted.state is ReportingLineCaseState.CONFLICT
    assert (await service.current_graph(at=NOW + timedelta(minutes=3))).edges == ()
    assert any(
        item["entry"].get("action_kind") == "human.reporting.graph_activation_retracted"
        for item in store.audit_entries
    )


async def test_graph_accepts_more_than_thirty_two_independent_edges() -> None:
    service = ReportingLineService(InMemoryStateStore())

    for index in range(40):
        candidate = _candidate(f"person-{index:02d}", f"manager-{index:02d}")
        await _activate(
            service,
            artifact=_artifact(candidate),
            candidate_id=candidate.candidate_id,
            confirmer=f"person-{index:02d}",
            owner=f"owner-{index:02d}",
        )

    graph = await service.current_graph(at=NOW + timedelta(minutes=3))
    assert len(graph.edges) == 40


async def test_graph_read_does_not_replay_historical_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportingLineService(InMemoryStateStore())
    candidate = _candidate("person-a", "person-b")
    await _activate(
        service,
        artifact=_artifact(candidate),
        candidate_id=candidate.candidate_id,
        confirmer="person-a",
        owner="owner",
    )

    def fail_if_replayed(_cases: object) -> None:
        raise AssertionError("historical graph validation ran on the read path")

    monkeypatch.setattr(graph_repository, "_validate_graph_history", fail_if_replayed)

    graph = await service.current_graph(at=NOW + timedelta(minutes=3))
    assert len(graph.edges) == 1


async def test_graph_aggregate_prunes_expired_authority_but_keeps_case_evidence() -> None:
    store = InMemoryStateStore()
    service = ReportingLineService(store)
    expired_candidate = _candidate("person-a", "person-b")
    expired = await _activate(
        service,
        artifact=_artifact(expired_candidate),
        candidate_id=expired_candidate.candidate_id,
        confirmer="person-a",
        owner="owner-a",
        effective_until=NOW + timedelta(days=1),
    )
    current_candidate = _candidate("person-c", "person-d")
    current = await _activate(
        service,
        artifact=_artifact(current_candidate),
        candidate_id=current_candidate.candidate_id,
        confirmer="person-c",
        owner="owner-c",
        at=NOW + timedelta(days=2),
    )

    graph_record = await store.read_state(GRAPH_KEY)
    assert graph_record is not None
    assert [item["case_id"] for item in graph_record["cases"]] == [current.case_id]
    assert (await service.get_case(expired.case_id)).state is ReportingLineCaseState.ACTIVE
    assert {
        edge.case_id
        for edge in (await service.current_graph(at=NOW + timedelta(days=2, minutes=3))).edges
    } == {current.case_id}


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
