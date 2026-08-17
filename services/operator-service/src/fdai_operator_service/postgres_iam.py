"""PostgreSQL projections and proposal-only outboxes for the Operator IAM family."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

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
    ConfigurationReviewCommand,
    DirectoryIdentity,
    HandoverGoalCommand,
    HilApprovalDecision,
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
    JsonMapping,
    KillSwitchCommand,
    ModelPreferenceCommand,
    RuntimeSettingsCommand,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamNotFoundError,
    IamPermissionError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
    StoredStatePage,
    StoredStateRecord,
)

_HIL_PARK_PREFIX = "hil_park:"
_HIL_DECISION_PREFIX = "operator-hil-decision:"
_ACCESS_GRANT_PREFIX = "execution-authorization:grant-request:"
_ACCESS_GRANT_SCAN_LIMIT = 1_000
_CANONICAL_GRANT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_SCOPE_REF = re.compile(r"^scope://[\x20-\x7E]{1,504}$")


@dataclass(frozen=True, slots=True)
class PostgresIamAdapters:
    """Implement IAM read ports and inert request outboxes over PostgreSQL."""

    store: PostgresFamilyStore

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
        """Read a bounded principal-scoped access-request projection."""
        payload = await self._projection("access-requests.list")
        items = _mapping_items(payload)
        visible = items[query.offset : query.offset + query.limit]
        return visible, _total(payload, items)

    async def submit(
        self,
        command: AccessRequestCommand | HandoverGoalCommand | KillSwitchCommand,
    ) -> JsonMapping:
        """Persist one IAM, handover, or kill-switch request as an inert proposal."""
        operation = _submit_operation(command)
        stored = await self._proposal(operation, command, _idempotency_key(command))
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
        operation = (
            "access-requests.review"
            if isinstance(command, AccessReviewCommand)
            else "assignments.review"
        )
        stored = await self._proposal(operation, command, _idempotency_key(command))
        request_id = (
            command.request_id if isinstance(command, AccessReviewCommand) else command.case_id
        )
        return {
            "request_id": request_id,
            "case_id": request_id,
            "proposal_id": stored.proposal_id,
            "status": "pending",
            "revision": getattr(command, "expected_revision", 0),
        }

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

    async def list_case_page(
        self,
        query: AssignmentCaseQuery,
    ) -> tuple[Sequence[JsonMapping], int]:
        """Read bounded assignment cases from the authoritative projection."""
        payload = await self._projection("assignments.cases")
        items = _mapping_items(payload)
        return items[query.offset : query.offset + query.limit], _total(payload, items)

    async def get_case(self, case_id: str) -> JsonMapping:
        """Read one exact assignment case from the materialized case projection."""
        payload = await self._projection("assignments.cases")
        item = next(
            (entry for entry in _mapping_items(payload) if entry.get("case_id") == case_id),
            None,
        )
        if item is None:
            raise IamNotFoundError(f"assignment case {case_id!r} was not found")
        return item

    async def create_case(self, command: AssignmentCreateCommand) -> JsonMapping:
        """Persist an assignment case intent without applying ownership or IAM effects."""
        stored = await self._proposal("assignments.create", command, command.idempotency_key)
        return {"case_id": stored.proposal_id, "proposal_id": stored.proposal_id, "revision": 1}

    async def submit_for_review(self, command: AssignmentTransitionCommand) -> JsonMapping:
        """Persist an assignment submission request for independent review."""
        stored = await self._proposal("assignments.submit", command, _idempotency_key(command))
        return {
            "case_id": command.case_id,
            "proposal_id": stored.proposal_id,
            "revision": command.expected_revision,
        }

    async def assignment_projection(self, query: AssignmentCaseQuery) -> JsonMapping:
        """Read the current materialized assignment projection."""
        del query
        return await self._projection("assignments.list")

    async def invitation_for_session(
        self,
        *,
        subject_ref: str,
        session_id: str,
    ) -> JsonMapping | None:
        """Read one matching handover invitation from the materialized projection."""
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

    async def projection(
        self,
        principal_id: str | None = None,
        *,
        can_manage_web_search: bool = False,
        refresh_model_catalog: bool = False,
        can_manage: bool = False,
    ) -> JsonMapping:
        """Read model or runtime settings without mutating their policy source."""
        del refresh_model_catalog
        operation = "model-settings" if principal_id is not None else "runtime-settings"
        payload = await self._projection(operation)
        if principal_id is not None:
            web_search = payload.get("web_search")
            if not isinstance(web_search, Mapping):
                raise IamUnavailableError("model settings projection has no web_search object")
            return {
                **payload,
                "web_search": {**web_search, "can_manage": can_manage_web_search},
            }
        return {
            **payload,
            "can_manage": can_manage,
        }

    async def set_preference(self, command: ModelPreferenceCommand) -> None:
        """Queue a revisioned narrator preference proposal."""
        await self._proposal("model-settings.preference", command, _idempotency_key(command))

    async def set_web_search_settings(self, command: WebSearchSettingsCommand) -> None:
        """Queue a revisioned web-search policy proposal."""
        await self._proposal("model-settings.web-search", command, _idempotency_key(command))

    async def update(self, command: RuntimeSettingsCommand) -> None:
        """Queue a revisioned runtime-settings proposal."""
        await self._proposal("runtime-settings.update", command, _idempotency_key(command))

    async def run(self, command: ConfigurationReviewCommand) -> JsonMapping:
        """Queue a configuration-review evidence campaign request."""
        stored = await self._proposal("configuration-review.run", command, command.run_id)
        return {"campaign_id": stored.proposal_id, "state": "pending"}

    async def resume(self, *, principal_id: str) -> JsonMapping:
        """Queue a resume request without running the evidence campaign in-process."""
        stored = await self._proposal(
            "configuration-review.resume",
            {"principal_id": principal_id},
            f"resume:{principal_id}",
        )
        return {"campaign_id": stored.proposal_id, "state": "pending"}

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        """Read one existing risk-gate HIL park record."""
        state = await self._state(f"{_HIL_PARK_PREFIX}{approval_id}")
        if state is None or state.get("status") != "pending":
            return None
        idempotency_key = state.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise IamUnavailableError("pending HIL record has no idempotency key")
        metadata = state.get("metadata", {})
        return HilPendingItem(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            submitter_oid=str(state.get("submitter_oid") or ""),
            metadata={str(key): str(value) for key, value in metadata.items()}
            if isinstance(metadata, Mapping)
            else {},
        )

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        """Read a previously recorded idempotent HIL decision."""
        state = await self._state(f"{_HIL_DECISION_PREFIX}{approval_id}")
        return None if state is None else _hil_receipt(state)

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        """Record a signed decision and queue no managed-resource effect."""
        pending = await self._find_state(
            prefix=_HIL_PARK_PREFIX,
            field="idempotency_key",
            value=command.idempotency_key,
        )
        if pending is None:
            raise IamNotFoundError("pending HIL item was not found")
        approval_id = pending.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            raise IamUnavailableError("pending HIL record has no approval id")
        stored = await self._proposal("hil.decision.record", command, command.idempotency_key)
        receipt = HilDecisionReceipt(
            approval_id=approval_id,
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref=stored.proposal_id,
        )
        state = _json_mapping(asdict(receipt))
        created = await self.store.create_state(f"{_HIL_DECISION_PREFIX}{approval_id}", state)
        if not created:
            existing = await self.get_decision_by_approval_id(approval_id)
            if existing is None:
                raise IamUnavailableError("recorded HIL decision disappeared")
            return replace(existing, already_recorded=True)
        return receipt

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        """Queue a recorded HIL decision for typed downstream transport."""
        await self._proposal(
            "hil.decision.enqueue",
            request,
            f"{request.receipt.idempotency_key}:delivery",
        )

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        """Mark only the durable outbox handoff, never the managed-resource effect."""
        delivered = replace(receipt, delivered=True)
        try:
            await self.store.write_state(
                f"{_HIL_DECISION_PREFIX}{receipt.approval_id}",
                _json_mapping(asdict(delivered)),
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError("HIL delivery receipt store is unavailable") from exc
        return delivered

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
    for key in ("principal_id", "actor_id", "actor_oid", "reviewer_ref"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    principal = payload.get("principal")
    return str(principal.get("oid")) if isinstance(principal, Mapping) else None


def _command_payload(command: object) -> dict[str, object]:
    if isinstance(command, Mapping):
        return _json_mapping(command)
    return _json_mapping(asdict(cast(Any, command)))


def _json_mapping(value: object) -> dict[str, object]:
    normalized = json.loads(json.dumps(value, default=str))
    if not isinstance(normalized, dict):
        raise ValueError("IAM adapter payload MUST serialize to a JSON object")
    return cast(dict[str, object], normalized)


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


def _hil_receipt(value: Mapping[str, object]) -> HilDecisionReceipt:
    try:
        return HilDecisionReceipt(
            approval_id=str(value["approval_id"]),
            idempotency_key=str(value["idempotency_key"]),
            decision=HilApprovalDecision(str(value["decision"])),
            approver_oid=str(value["approver_oid"]),
            decided_at=_datetime(value.get("decided_at"), "decided_at"),
            receipt_ref=str(value["receipt_ref"]),
            already_recorded=value.get("already_recorded") is True,
            delivered=value.get("delivered") is True,
        )
    except KeyError as exc:
        raise IamUnavailableError("stored HIL decision receipt is malformed") from exc


__all__ = ["PostgresIamAdapters"]
