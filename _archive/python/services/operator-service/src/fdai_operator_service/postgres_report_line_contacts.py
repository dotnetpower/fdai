"""PostgreSQL requester-contact projection and durable consent outbox."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts import ReportLineContactCommand

from fdai_operator_service.families.iam.contracts import ReportLineContactContext
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)

_HIL_PARK_PREFIX = "hil_park:"


@dataclass(frozen=True, slots=True)
class PostgresReportLineContacts:
    """Expose requester-owned contact requests and persist no-authority choices."""

    store: PostgresFamilyStore
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def get_report_line_contact_context(
        self,
        approval_id: str,
    ) -> ReportLineContactContext | None:
        state = await self._state(_HIL_PARK_PREFIX + approval_id)
        if state is None or state.get("status") != "awaiting_contact_consent":
            return None
        route = state.get("report_line_route")
        context = state.get("approval_context")
        action = state.get("action")
        consent_id = state.get("contact_consent_id")
        requester = state.get("submitter_oid")
        if (
            not isinstance(route, Mapping)
            or not isinstance(context, Mapping)
            or not isinstance(action, Mapping)
            or not isinstance(consent_id, str)
            or not consent_id
            or not isinstance(requester, str)
            or requester != requester.strip().casefold()
        ):
            raise IamUnavailableError("report-line contact context is malformed")
        route_subjects = _route_subjects(route)
        approval_expires_at = _aware_timestamp(
            context.get("expires_at"),
            "report-line approval expiry",
        )
        consent_state = await self._state("human_reporting:approval-consent:" + consent_id)
        if (
            consent_state is None
            or consent_state.get("state") != "pending"
            or consent_state.get("requester_ref") != requester
            or consent_state.get("action_digest") != state.get("action_hash")
            or consent_state.get("route_digest") != route.get("route_digest")
            or consent_state.get("path_revision") != route.get("path_revision")
        ):
            raise IamUnavailableError("report-line contact consent evidence is unavailable")
        expires_at = _aware_timestamp(
            consent_state.get("expires_at"),
            "report-line contact consent expiry",
        )
        consent_requested_at = _aware_timestamp(
            consent_state.get("created_at"),
            "report-line contact consent creation",
        )
        if (
            consent_requested_at >= expires_at
            or expires_at > approval_expires_at
            or expires_at <= _aware_timestamp(self.clock(), "report-line contact clock")
        ):
            return None
        revision = consent_state.get("revision")
        action_type = action.get("action_type")
        target_ref = action.get("target_resource_ref")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
            or not isinstance(action_type, str)
            or not action_type
            or not isinstance(target_ref, str)
            or not target_ref
        ):
            raise IamUnavailableError("report-line contact action context is malformed")
        return ReportLineContactContext(
            approval_id=approval_id,
            requester_ref=requester,
            consent_id=consent_id,
            consent_revision=revision,
            action_type=action_type,
            target_ref=target_ref,
            route_subjects=route_subjects,
            consent_requested_at=consent_requested_at,
            expires_at=expires_at,
        )

    async def list_report_line_contact_contexts(
        self,
        *,
        requester_ref: str,
        limit: int,
    ) -> tuple[ReportLineContactContext, ...]:
        requester = requester_ref.strip().casefold()
        if not requester or requester != requester_ref or not 1 <= limit <= 100:
            raise ValueError("report-line contact query is invalid")
        try:
            page = await self.store.read_state_page(
                prefix=_HIL_PARK_PREFIX,
                limit=1_000,
                match_field="status",
                match_value="awaiting_contact_consent",
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("report-line contact source is unavailable") from exc
        if page.truncated:
            raise IamUnavailableError("report-line contact coverage is incomplete")
        contexts: list[ReportLineContactContext] = []
        for record in page.records:
            state = record.value
            if (
                state.get("status") != "awaiting_contact_consent"
                or str(state.get("submitter_oid") or "").casefold() != requester
            ):
                continue
            approval_id = state.get("approval_id")
            if not isinstance(approval_id, str) or not approval_id:
                raise IamUnavailableError("report-line contact source is malformed")
            context = await self.get_report_line_contact_context(approval_id)
            if context is not None:
                contexts.append(context)
        contexts.sort(key=lambda item: (item.expires_at, item.approval_id))
        return tuple(contexts[:limit])

    async def enqueue_report_line_contact(
        self,
        command: ReportLineContactCommand,
    ) -> None:
        try:
            await self.store.append_proposal(
                family="iam",
                operation="hil.report-line-contact.enqueue",
                principal_id=command.requester_ref,
                idempotency_key=command.idempotency_key,
                payload=command.model_dump(mode="json"),
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _state(self, key: str) -> dict[str, object] | None:
        try:
            return await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("report-line contact state is unavailable") from exc


def _route_subjects(route: Mapping[str, object]) -> tuple[str, ...]:
    rungs = route.get("rungs")
    if not isinstance(rungs, list) or not rungs:
        raise IamUnavailableError("report-line contact route is malformed")
    subjects: list[str] = []
    for rung in rungs:
        if not isinstance(rung, Mapping):
            raise IamUnavailableError("report-line contact route is malformed")
        subject = rung.get("subject_ref")
        if not isinstance(subject, str) or not subject:
            raise IamUnavailableError("report-line contact route is malformed")
        subjects.append(subject)
    return tuple(subjects)


def _aware_timestamp(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IamUnavailableError(f"{label} is malformed") from exc
    else:
        raise IamUnavailableError(f"{label} is malformed")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IamUnavailableError(f"{label} is not timezone-aware")
    return parsed.astimezone(UTC)


__all__ = ["PostgresReportLineContacts"]
