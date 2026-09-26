"""PostgreSQL projections and proposal-only outboxes for the Operator IAM family."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts import OperatorRole

from fdai_operator_service.families.iam.contracts import (
    AccessGrantDecisionCommand,
    AccessGrantDecisionResult,
    AccessGrantRecord,
    AccessGrantSnapshot,
    AccessGrantSnapshotQuery,
    AccessRequestCommand,
    AccessRequestQuery,
    AccessReviewCommand,
    AssignmentCaseQuery,
    AssignmentCreateCommand,
    AssignmentTransitionCommand,
    DirectoryIdentity,
    DirectoryStatus,
    HandoverGoalCommand,
    IamPrincipal,
    JsonMapping,
    KillSwitchCommand,
    ModelCatalogReader,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.model_lifecycle_startup import OperatorResolvedModelsRevisionOwner
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)
from fdai_operator_service.postgres_hil_decision import (
    HilDecisionStore,
)
from fdai_operator_service.postgres_iam_access_projection import (
    access_request_from_proposal as _access_request_from_proposal,
)
from fdai_operator_service.postgres_iam_access_projection import (
    assignment_case_from_proposal as _assignment_case_from_proposal,
)
from fdai_operator_service.postgres_iam_access_projection import (
    assignment_projection_item as _assignment_projection_item,
)
from fdai_operator_service.postgres_iam_access_projection import (
    project_assignment_case as _project_assignment_case,
)
from fdai_operator_service.postgres_iam_access_projection import (
    reviewed_access_request as _reviewed_access_request,
)
from fdai_operator_service.postgres_iam_configuration import PostgresIamConfigurationMixin
from fdai_operator_service.postgres_iam_hil import PostgresIamHilMixin

_HIL_PARK_PREFIX = "hil_park:"
_HIL_DECISION_PREFIX = "operator-hil-decision:"
_HIL_CALLBACK_AUDIT_PREFIX = "operator-hil-callback-audit:"
_ACCESS_GRANT_PREFIX = "execution-authorization:grant-request:"
_ACCESS_GRANT_SCAN_LIMIT = 1_000
_IAM_PROPOSAL_PREFIX = "operator-proposal:iam:"
_IAM_PROPOSAL_SCAN_LIMIT = 1_000
_CANONICAL_GRANT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_SCOPE_REF = re.compile(r"^scope://[\x20-\x7E]{1,504}$")
_MODEL_BINDING_POLICY_KEY = "operator-model-binding-policy:current"
_DOCUMENT_OCR_POLICY_KEY = "operator-document-ocr-policy:current"
_DOCUMENT_OCR_PLAN_KEY = "operator-document-ocr-plan:current"
_RUNTIME_SETTINGS_POLICY_KEY = "runtime-settings:policy"
_TEAMS_A1_ONBOARDING_PLAN_KEY = "operator-teams-a1-onboarding-plan:current"


@dataclass(frozen=True, slots=True)
class PostgresIamAdapters(PostgresIamConfigurationMixin, PostgresIamHilMixin):
    """Implement IAM read ports and inert request outboxes over PostgreSQL."""

    store: PostgresFamilyStore
    model_catalog: ModelCatalogReader | None = None
    hil_decisions: HilDecisionStore | None = None
    narrator_revision_owner: OperatorResolvedModelsRevisionOwner | None = None

    async def read_state(self, key: str) -> dict[str, object] | None:
        """Expose read-only shared state needed by additive IAM projections."""

        try:
            return await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc

    async def snapshot(self, query: AccessGrantSnapshotQuery) -> AccessGrantSnapshot:
        """Read the reviewer-scoped access-grant snapshot for SSE replay."""
        page = await self._pending_grant_page()
        if page.truncated:
            raise IamUnavailableError("access-grant review coverage cannot be proven complete")
        records = page.records
        generated_at = datetime.now(tz=UTC)
        # A decided request leaves the pending view, so the cursor is carried forward
        # rather than allowed to regress with the page it no longer contains.
        sequence = max(_snapshot_sequence(records), query.after_sequence or 0)
        reviewer = query.reviewer_ref.casefold()
        reviewer_roles = {role.casefold() for role in query.reviewer_roles}
        visible = [
            _access_grant(record.value)
            for record in records
            if reviewer_roles and _reviewable(record.value, reviewer, reviewer_roles, generated_at)
        ]
        # Oldest request first, so a busy queue cannot starve the longest-waiting approval.
        visible.sort(key=lambda item: (item.requested_at, item.request_id))
        return AccessGrantSnapshot(
            sequence=sequence,
            generated_at=generated_at,
            requests=tuple(visible[: query.limit]),
        )

    async def decide(self, command: AccessGrantDecisionCommand) -> AccessGrantDecisionResult:
        """Persist a revision-fenced access decision without applying permission."""
        record = await self._state(f"{_ACCESS_GRANT_PREFIX}{command.request_id}")
        if record is None:
            raise IamNotFoundError("access grant request does not exist")
        if str(record.get("status") or "") != "pending":
            raise IamConflictError("access grant request is not pending")
        # Deciding is bound to the same predicate as seeing, so the two cannot drift apart.
        if not _reviewable(
            record,
            command.reviewer_ref.casefold(),
            {role.casefold() for role in command.reviewer_roles},
            command.decided_at,
        ):
            raise IamPermissionError("reviewer is not eligible to decide this access grant")
        quorum = _integer(record, "quorum")
        approved_by = record.get("approved_by", [])
        if quorum < 1 or not isinstance(approved_by, list) or len(approved_by) > quorum:
            raise IamUnavailableError("access-grant approval policy is malformed")
        await self._proposal("access-grants.decide", command, _decision_key(command))
        return AccessGrantDecisionResult(
            request_id=command.request_id,
            status="pending",
            revision=_integer(record, "revision"),
            approved_count=len(approved_by),
            quorum=quorum,
            reviewed_at=command.decided_at,
        )

    async def list_request_page(
        self,
        query: AccessRequestQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        """Project durable access proposals and independent review decisions."""
        items = await self._access_requests()
        if not _can_manage_group_membership(query.principal):
            requester = query.principal.oid.casefold()
            items = [
                item
                for item in items
                if str(item.get("requester_oid") or "").casefold() == requester
            ]
        total = len(items)
        return items[query.offset : query.offset + query.limit], total

    async def submit(
        self,
        command: AccessRequestCommand | HandoverGoalCommand | KillSwitchCommand,
    ) -> JsonMapping:
        """Persist one IAM, handover, or kill-switch request as an inert proposal."""
        operation = _submit_operation(command)
        stored = await self._proposal(operation, command, _idempotency_key(command))
        if isinstance(command, AccessRequestCommand):
            return _access_request_from_proposal(stored.record)
        return {
            "request_id": stored.proposal_id,
            "proposal_id": stored.proposal_id,
            "status": "pending",
            "dispatch_status": "pending",
            "duplicate": stored.duplicate,
        }

    async def review(
        self,
        command: AccessReviewCommand | AssignmentTransitionCommand,
    ) -> JsonMapping:
        """Persist a review request without changing identity-provider or ownership state."""
        if isinstance(command, AccessReviewCommand):
            request = next(
                (
                    item
                    for item in await self._access_requests()
                    if item.get("request_id") == command.request_id
                ),
                None,
            )
            if request is None:
                raise IamNotFoundError("access request does not exist")
            if (
                str(request.get("requester_oid") or "").casefold()
                == command.principal.oid.casefold()
            ):
                raise IamPermissionError("requester MUST NOT approve their own request")
            if request.get("status") != "pending":
                raise IamConflictError("access request already has a decision")
        else:
            assignment = await self.get_case(command.case_id)
            if assignment.get("state") != "pending_review":
                raise IamConflictError("assignment case is not pending review")
            if assignment.get("revision") != command.expected_revision:
                raise IamConflictError("assignment case revision is stale")
            intent = assignment.get("intent")
            if not isinstance(intent, Mapping):
                raise IamUnavailableError("assignment case intent is malformed")
            reviewer = command.principal.oid.casefold()
            subject = intent.get("subject")
            subject_id = subject.get("subject_id") if isinstance(subject, Mapping) else None
            if reviewer in {
                str(intent.get("requester_ref") or "").casefold(),
                str(subject_id or "").casefold(),
            }:
                raise IamPermissionError(
                    "assignment requester and target MUST NOT review their own case"
                )
            if any(
                str(item.get("reviewer_ref") or "").casefold() == reviewer
                for item in assignment.get("reviews", [])
                if isinstance(item, Mapping)
            ):
                raise IamConflictError("assignment reviewer already recorded a decision")
        operation = (
            "access-requests.review"
            if isinstance(command, AccessReviewCommand)
            else "assignments.review"
        )
        stored = await self._proposal(operation, command, _idempotency_key(command))
        if isinstance(command, AccessReviewCommand):
            if request is None:
                raise IamUnavailableError("access request review lost its request projection")
            return _reviewed_access_request(request, stored.record)
        return await self.get_case(command.case_id)

    async def search(self, query: str, *, limit: int) -> Sequence[DirectoryIdentity]:
        """Search only the materialized human-directory projection."""
        identities = await self._directory()
        needle = query.casefold().strip()
        return tuple(
            item
            for item in identities
            if not needle
            or needle in item.username.casefold()
            or needle in (item.display_name or "").casefold()
        )[:limit]

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int,
    ) -> Sequence[DirectoryIdentity]:
        """Read the materialized role roster without calling the identity provider."""
        del role_group_ids
        return (await self._directory())[:limit]

    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        """Resolve one exact materialized human identity."""
        return next(
            (item for item in await self._directory() if item.subject_id == subject_id),
            None,
        )

    async def get_steward_subject_by_id(
        self,
        subject_id: str,
        *,
        kind: str,
    ) -> DirectoryIdentity | None:
        """Resolve an exact materialized stewardship user or group."""
        identity = await self.get_by_subject_id(subject_id)
        if identity is None:
            return None
        expected_type = "group" if kind == "group" else "person"
        return identity if identity.principal_type == expected_type else None

    async def directory_status(self) -> DirectoryStatus:
        """Return materialized directory availability without inferred freshness."""
        await self._projection("directory")
        return DirectoryStatus(
            source="materialized-projection",
            availability="available",
        )

    async def _access_requests(self) -> list[dict[str, object]]:
        page = await self._iam_proposal_page()
        reviews: dict[str, Mapping[str, object]] = {}
        requests: list[dict[str, object]] = []
        for record in page.records:
            operation = record.value.get("operation")
            if operation == "access-requests.review":
                payload = record.value.get("payload")
                if isinstance(payload, Mapping):
                    request_id = payload.get("request_id")
                    if isinstance(request_id, str):
                        reviews[request_id] = record.value
            elif operation == "access-requests.submit":
                requests.append(_access_request_from_proposal(record.value))
        requests.sort(
            key=lambda item: (str(item.get("requested_at") or ""), str(item["request_id"])),
            reverse=True,
        )
        return [
            _reviewed_access_request(item, reviews[str(item["request_id"])])
            if str(item["request_id"]) in reviews
            else item
            for item in requests
        ]

    async def _iam_proposal_page(self) -> StoredStatePage:
        try:
            page = await self.store.read_state_page(
                prefix=_IAM_PROPOSAL_PREFIX,
                limit=_IAM_PROPOSAL_SCAN_LIMIT,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        if page.truncated:
            raise IamUnavailableError("IAM proposal coverage is incomplete")
        return page

    async def list_case_page(
        self,
        query: AssignmentCaseQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        """Project bounded assignment cases from durable proposals."""
        items = await self._assignment_cases()
        return items[query.offset : query.offset + query.limit], len(items)

    async def get_case(self, case_id: str) -> JsonMapping:
        """Read one exact assignment case from durable proposals."""
        item = next(
            (entry for entry in await self._assignment_cases() if entry.get("case_id") == case_id),
            None,
        )
        if item is None:
            raise IamNotFoundError(f"assignment case {case_id!r} was not found")
        return item

    async def create_case(self, command: AssignmentCreateCommand) -> JsonMapping:
        """Persist an assignment case intent without applying ownership or IAM effects."""
        stored = await self._proposal("assignments.create", command, command.idempotency_key)
        return _assignment_case_from_proposal(stored.record)

    async def submit_for_review(self, command: AssignmentTransitionCommand) -> JsonMapping:
        """Persist an assignment submission request for independent review."""
        current = await self.get_case(command.case_id)
        if current.get("state") != "draft":
            return current
        if current.get("revision") != command.expected_revision:
            raise IamConflictError("assignment case revision is stale")
        await self._proposal("assignments.submit", command, _idempotency_key(command))
        return await self.get_case(command.case_id)

    async def assignment_projection(self, query: AssignmentCaseQuery) -> JsonMapping:
        """Join durable cases into an explicit observation-only projection."""
        cases = await self._assignment_cases()
        page = cases[query.offset : query.offset + query.limit]
        return {
            "items": [_assignment_projection_item(item) for item in page],
            "total": len(cases),
            "next_cursor": (
                query.offset + len(page) if query.offset + len(page) < len(cases) else None
            ),
            "directory_availability": "available",
            "case_projection_truncated": False,
        }

    async def _assignment_cases(self) -> list[dict[str, object]]:
        page = await self._iam_proposal_page()
        submissions: dict[str, Mapping[str, object]] = {}
        reviews: dict[str, list[Mapping[str, object]]] = {}
        cases: list[dict[str, object]] = []
        for record in page.records:
            operation = record.value.get("operation")
            payload = record.value.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if payload.get("case_kind") is not None:
                continue
            case_id = payload.get("case_id")
            if operation == "assignments.create":
                cases.append(_assignment_case_from_proposal(record.value))
            elif operation == "assignments.submit" and isinstance(case_id, str):
                submissions[case_id] = record.value
            elif operation == "assignments.review" and isinstance(case_id, str):
                reviews.setdefault(case_id, []).append(record.value)
        projected = [
            _project_assignment_case(
                item,
                submitted=submissions.get(str(item["case_id"])),
                reviews=reviews.get(str(item["case_id"]), []),
            )
            for item in cases
        ]
        from fdai_operator_service.assignment_projection import join_assignment_case

        try:
            joined = [await join_assignment_case(self.store, item) for item in projected]
        except (ValueError, PostgresFamilyStoreUnavailable) as exc:
            raise IamUnavailableError("assignment Core projection is unavailable") from exc
        joined.sort(key=lambda item: str(item["case_id"]), reverse=True)
        return joined

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        roles: frozenset[OperatorRole],
        session_id: str,
    ) -> JsonMapping | None:
        """Read one matching handover invitation from the materialized projection."""
        del roles
        payload = await self._projection("handover.invitations")
        return next(
            (
                item
                for item in _mapping_items(payload)
                if item.get("subject_ref") == subject_ref and item.get("session_id") == session_id
            ),
            None,
        )

    async def get_goal(self, goal_id: str) -> JsonMapping:
        """Read one exact handover goal from the materialized projection."""
        payload = await self._projection("handover.goals")
        item = next(
            (entry for entry in _mapping_items(payload) if entry.get("goal_id") == goal_id),
            None,
        )
        if item is None:
            raise IamNotFoundError(f"handover goal {goal_id!r} was not found")
        return item

    async def _directory(self) -> tuple[DirectoryIdentity, ...]:
        payload = await self._projection("directory")
        return tuple(_directory_identity(item) for item in _mapping_items(payload))

    async def _projection(self, operation: str) -> dict[str, object]:
        try:
            return await self.store.read_projection(family="iam", operation=operation)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _proposal(
        self,
        operation: str,
        command: object,
        idempotency_key: str,
    ) -> StoredProposal:
        payload = _command_payload(command)
        try:
            return await self.store.append_proposal(
                family="iam",
                operation=operation,
                principal_id=_principal_id(payload),
                idempotency_key=idempotency_key,
                payload=payload,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc

    async def _state(self, key: str) -> dict[str, object] | None:
        try:
            return await self.store.read_state(key)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc

    async def _find_state(self, *, prefix: str, field: str, value: str) -> dict[str, object] | None:
        try:
            return await self.store.find_state(prefix=prefix, field=field, value=value)
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc

    async def _pending_grant_page(self) -> StoredStatePage:
        try:
            return await self.store.read_state_page(
                prefix=_ACCESS_GRANT_PREFIX,
                limit=_ACCESS_GRANT_SCAN_LIMIT,
                match_field="status",
                match_value="pending",
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("authoritative IAM state is unavailable") from exc


def _submit_operation(command: object) -> str:
    if isinstance(command, AccessRequestCommand):
        return "access-requests.submit"
    if isinstance(command, HandoverGoalCommand):
        return "handover.submit"
    return "kill-switch.submit"


def _can_manage_group_membership(principal: IamPrincipal) -> bool:
    return any(role.value == "Owner" for role in principal.roles)


def _idempotency_key(command: object) -> str:
    for name in ("idempotency_key", "request_id", "run_id"):
        value = getattr(command, name, None)
        if isinstance(value, str) and value:
            return value
    payload = _command_payload(command)
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def _principal_id(payload: Mapping[str, object]) -> str | None:
    for key in (
        "principal_id",
        "actor_id",
        "actor_oid",
        "reviewer_ref",
        "requester_ref",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    principal = payload.get("principal")
    return str(principal.get("oid")) if isinstance(principal, Mapping) else None


def _command_payload(command: object) -> dict[str, object]:
    if isinstance(command, Mapping):
        return _json_mapping(command)
    payload = _json_mapping(asdict(cast(Any, command)))
    if isinstance(command, AssignmentCreateCommand) and command.revocation is None:
        # Preserve the exact immutable request digest of grants accepted before version 1.1.0.
        payload.pop("revocation", None)
    return payload


def _json_mapping(value: object) -> dict[str, object]:
    normalized = json.loads(json.dumps(value, default=_json_default))
    if not isinstance(normalized, dict):
        raise ValueError("IAM adapter payload MUST serialize to a JSON object")
    return cast(dict[str, object], normalized)


def _json_default(value: object) -> object:
    """Encode command values deterministically so a durable digest is process-stable."""
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _mapping_items(payload: Mapping[str, object]) -> tuple[JsonMapping, ...]:
    raw = payload.get("items", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise IamUnavailableError("authoritative IAM projection items are malformed")
    return tuple(cast(JsonMapping, item) for item in raw)


def _total(payload: Mapping[str, object], items: Sequence[object]) -> int:
    raw = payload.get("total", len(items))
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise IamUnavailableError("authoritative IAM projection total is malformed")
    return raw


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IamUnavailableError(f"authoritative IAM projection {key} is malformed")
    return value


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed") from exc
    if parsed.tzinfo is None:
        raise IamUnavailableError(f"authoritative IAM projection {name} has no timezone")
    return parsed.astimezone(UTC)


def _access_grant(value: object) -> AccessGrantRecord:
    if not isinstance(value, Mapping):
        raise IamUnavailableError("access-grant projection item is malformed")
    quorum = _integer(value, "quorum")
    if quorum < 1:
        raise IamUnavailableError("access-grant projection quorum is malformed")
    return AccessGrantRecord(
        request_id=_grant_identifier(value.get("request_id"), "request_id"),
        correlation_id=_grant_identifier(value.get("original_action_id"), "original_action_id"),
        capability_id=_grant_identifier(value.get("capability_id"), "capability_id"),
        scope_ref=_grant_scope(value.get("scope_ref")),
        grant_mode=_grant_identifier(value.get("grant_mode"), "grant_mode"),
        requested_at=_datetime(value.get("requested_at"), "requested_at"),
        expires_at=_datetime(value.get("expires_at"), "expires_at"),
        quorum=quorum,
        status=str(value.get("status") or ""),
        revision=_integer(value, "revision"),
    )


def _grant_identifier(value: object, name: str) -> str:
    """Bound one projected identifier to the exact range the browser contract accepts."""
    if not isinstance(value, str) or not _CANONICAL_GRANT_ID.match(value):
        raise IamUnavailableError(f"authoritative IAM projection {name} is malformed")
    return value


def _grant_scope(value: object) -> str:
    if not isinstance(value, str) or not _SCOPE_REF.match(value):
        raise IamUnavailableError("authoritative IAM projection scope_ref is malformed")
    return value


def _decision_key(command: AccessGrantDecisionCommand) -> str:
    """Fence one reviewer's decision on one revision so a quorum can still accumulate."""
    reviewer = hashlib.sha256(command.reviewer_ref.encode()).hexdigest()[:32]
    return f"{command.request_id}:{command.expected_revision}:{reviewer}"


def _snapshot_sequence(records: Sequence[StoredStateRecord]) -> int:
    """Derive a non-decreasing replay cursor from the newest authoritative write time."""
    return max((int(record.updated_at.timestamp() * 1_000_000) for record in records), default=0)


def _reviewable(
    value: Mapping[str, object],
    reviewer: str,
    reviewer_roles: set[str],
    now: datetime,
) -> bool:
    """Report whether one authoritative grant request is reviewable by this principal."""
    if str(value.get("status") or "") != "pending":
        return False
    if _datetime(value.get("expires_at"), "expires_at") <= now:
        return False
    if str(value.get("requester_ref") or "").casefold() == reviewer:
        return False
    approver_roles = value.get("approver_roles")
    if not isinstance(approver_roles, list):
        raise IamUnavailableError("access-grant approver roles are malformed")
    return bool(reviewer_roles.intersection(str(role).casefold() for role in approver_roles))


def _directory_identity(value: Mapping[str, Any]) -> DirectoryIdentity:
    roles = value.get("roles", [])
    if not isinstance(roles, list):
        raise IamUnavailableError("directory identity roles are malformed")
    return DirectoryIdentity(
        provider=str(value.get("provider") or ""),
        subject_id=str(value.get("subject_id") or ""),
        username=str(value.get("username") or ""),
        display_name=str(value["display_name"]) if value.get("display_name") is not None else None,
        active=value.get("active") is True,
        principal_type=str(value.get("principal_type") or "person"),
        roles=tuple(str(role) for role in roles),
    )


__all__ = ["PostgresIamAdapters"]
