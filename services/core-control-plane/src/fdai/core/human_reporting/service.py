"""StateStore-backed reporting-line confirmation and Owner-review lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai_service_contracts import ReportingLineDraftArtifact, ReportingLineDraftOutcome

from fdai.core.human_reporting.graph import ReportingGraphSnapshot
from fdai.core.human_reporting.graph_repository import (
    activate_reporting_case,
    load_reporting_graph,
)
from fdai.core.human_reporting.model import (
    EndpointConfirmation,
    EndpointDecision,
    OwnerDecision,
    OwnerReview,
    ReportingLineCase,
    ReportingLineCaseState,
    ReportingLineModelError,
    normalize_principal,
    reporting_instant,
)
from fdai.core.human_reporting.repository import (
    create_case_state,
    list_case_states,
    load_case_state,
    persist_case_state,
    reporting_line_case_id,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class ReportingLineService:
    """Create, confirm, review, and project immutable reporting edges."""

    store: StateStore
    default_validity: timedelta = timedelta(days=90)

    def __post_init__(self) -> None:
        if not timedelta(days=1) <= self.default_validity <= timedelta(days=366):
            raise ValueError("reporting-line default validity MUST be in [1, 366] days")

    async def create_case(
        self,
        *,
        principal: Principal,
        artifact: ReportingLineDraftArtifact,
        candidate_id: str,
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
        supersedes_case_id: str | None = None,
        now: datetime | None = None,
    ) -> ReportingLineCase:
        """Create or replay one exact resolved document edge."""

        if not has_capability(principal.roles, Capability.AUTHOR_DRAFT_PR):
            raise PermissionError("reporting-line import requires Contributor or higher")
        if artifact.outcome is not ReportingLineDraftOutcome.DRAFTED:
            raise ReportingLineModelError("reporting-line artifact has no reviewable candidates")
        candidate = next(
            (item for item in artifact.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise ReportingLineModelError("reporting-line candidate was not found in the artifact")
        recorded_at = reporting_instant(now or datetime.now(tz=UTC))
        starts = reporting_instant(effective_from or candidate.effective_from or recorded_at)
        ends = reporting_instant(
            effective_until or candidate.effective_until or (starts + self.default_validity)
        )
        case_id = reporting_line_case_id(str(artifact.upload_id), candidate.candidate_id)
        requested = ReportingLineCase.from_candidate(
            case_id=case_id,
            artifact_upload_id=artifact.upload_id,
            artifact_document_id=artifact.document_id,
            artifact_version_id=artifact.version_id,
            artifact_source_sha256=artifact.source_sha256,
            candidate=candidate,
            requester_ref=principal.oid,
            effective_from=starts,
            effective_until=ends,
            recorded_at=recorded_at,
            supersedes_case_id=supersedes_case_id,
        )
        if supersedes_case_id is not None:
            previous = await load_case_state(self.store, supersedes_case_id)
            if (
                previous.state is not ReportingLineCaseState.ACTIVE
                or not previous.effective_from <= recorded_at < previous.effective_until
            ):
                raise ReportingLineModelError(
                    "a reporting-line replacement requires an active prior edge"
                )
            if previous.subject_ref != requested.subject_ref:
                raise ReportingLineModelError(
                    "a reporting-line replacement MUST keep the same subject"
                )
        return await create_case_state(
            self.store,
            requested,
            actor_ref=principal.oid,
            at=recorded_at,
        )

    async def get_case(self, case_id: str) -> ReportingLineCase:
        return await load_case_state(self.store, case_id)

    async def list_cases(self, *, limit: int = 5_000) -> tuple[ReportingLineCase, ...]:
        return await list_case_states(self.store, limit=limit)

    async def confirm(
        self,
        *,
        principal: Principal,
        case_id: str,
        expected_revision: int,
        decision: EndpointDecision,
        edge_digest: str,
        now: datetime | None = None,
    ) -> ReportingLineCase:
        """Record one relationship endpoint decision without granting approval authority."""

        current = await self.get_case(case_id)
        actor = normalize_principal(principal.oid)
        if actor not in {current.subject_ref, current.manager_ref}:
            raise PermissionError("only a reporting-line endpoint may confirm the relationship")
        if current.edge_digest != edge_digest:
            raise ReportingLineModelError("reporting-line confirmation digest is stale")
        if current.revision != expected_revision:
            raise ReportingLineModelError("reporting-line confirmation revision is stale")
        if current.state not in {
            ReportingLineCaseState.PENDING_CONFIRMATION,
            ReportingLineCaseState.PENDING_OWNER_REVIEW,
        }:
            raise ReportingLineModelError("reporting-line case is not awaiting confirmation")
        if current.confirmation is not None:
            if (
                current.confirmation.principal_ref == actor
                and current.confirmation.decision is decision
            ):
                return current
            if decision is EndpointDecision.CONFIRM:
                return current
        decided_at = reporting_instant(now or datetime.now(tz=UTC))
        confirmation = EndpointConfirmation(
            principal_ref=actor,
            decision=decision,
            decided_at=decided_at,
            edge_digest=current.edge_digest,
        )
        target = (
            ReportingLineCaseState.CONFLICT
            if decision is EndpointDecision.REJECT
            else ReportingLineCaseState.PENDING_OWNER_REVIEW
        )
        candidate = replace(
            current,
            state=target,
            revision=current.revision + 1,
            recorded_at=decided_at,
            confirmation=confirmation,
            owner_review=None,
        )
        return await persist_case_state(
            self.store,
            current,
            candidate,
            actor_ref=actor,
            action_kind="human.reporting.endpoint_decided",
            at=decided_at,
        )

    async def review(
        self,
        *,
        principal: Principal,
        case_id: str,
        expected_revision: int,
        decision: OwnerDecision,
        edge_digest: str,
        now: datetime | None = None,
    ) -> ReportingLineCase:
        """Apply one independent current Owner review to a confirmed edge."""

        if Role.OWNER not in principal.roles:
            raise PermissionError("reporting-line review requires the Owner role")
        current = await self.get_case(case_id)
        if current.state is not ReportingLineCaseState.PENDING_OWNER_REVIEW:
            raise ReportingLineModelError("reporting-line case is not pending Owner review")
        if current.revision != expected_revision or current.edge_digest != edge_digest:
            raise ReportingLineModelError("reporting-line Owner review is stale")
        if current.confirmation is None:
            raise ReportingLineModelError("reporting-line Owner review requires confirmation")
        actor = normalize_principal(principal.oid)
        if actor in {
            current.requester_ref,
            current.subject_ref,
            current.manager_ref,
            current.confirmation.principal_ref,
        }:
            raise PermissionError("reporting-line Owner review MUST be independent")
        decided_at = reporting_instant(now or datetime.now(tz=UTC))
        if decided_at >= current.effective_until:
            raise ReportingLineModelError("expired reporting-line evidence cannot be activated")
        review = OwnerReview(
            principal_ref=actor,
            decision=decision,
            decided_at=decided_at,
            edge_digest=current.edge_digest,
        )
        target = (
            ReportingLineCaseState.ACTIVE
            if decision is OwnerDecision.APPROVE
            else ReportingLineCaseState.REJECTED
        )
        candidate = replace(
            current,
            state=target,
            revision=current.revision + 1,
            recorded_at=decided_at,
            owner_review=review,
        )
        if target is ReportingLineCaseState.ACTIVE:
            await activate_reporting_case(
                self.store,
                candidate,
                actor_ref=actor,
                at=decided_at,
            )
        return await persist_case_state(
            self.store,
            current,
            candidate,
            actor_ref=actor,
            action_kind="human.reporting.owner_reviewed",
            at=decided_at,
        )

    async def current_graph(self, *, at: datetime | None = None) -> ReportingGraphSnapshot:
        """Return the complete current graph or fail closed on incomplete coverage."""

        return await load_reporting_graph(
            self.store,
            at=reporting_instant(at or datetime.now(tz=UTC)),
        )


def report_line_case_result(
    case: ReportingLineCase,
    *,
    proposal_id: str,
    request_digest: str,
    operator_case_id: str,
) -> dict[str, object]:
    """Return the content-free cross-service materialization result."""

    try:
        UUID(case.case_id)
    except ValueError as exc:  # pragma: no cover - model invariant
        raise ReportingLineModelError("reporting-line case id is invalid") from exc
    return {
        "schema_version": "1.3.0",
        "proposal_id": proposal_id,
        "request_digest": request_digest,
        "operator_case_id": operator_case_id,
        "case_id": case.case_id,
        "state": case.state.value,
        "revision": case.revision,
        "ownership_effect_ref": None,
        "iam_effect_ref": None,
        "execution_authority": False,
    }


__all__ = ["ReportingLineService", "report_line_case_result"]
