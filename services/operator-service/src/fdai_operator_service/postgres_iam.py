"""PostgreSQL projections and proposal-only outboxes for the Operator IAM family."""

from __future__ import annotations

import hashlib
import json
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
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
)

_HIL_PARK_PREFIX = "hil_park:"
_HIL_DECISION_PREFIX = "operator-hil-decision:"


@dataclass(frozen=True, slots=True)
class PostgresIamAdapters:
    """Implement IAM read ports and inert request outboxes over PostgreSQL."""

    store: PostgresFamilyStore

    async def snapshot(self, query: AccessGrantSnapshotQuery) -> AccessGrantSnapshot:
        """Read the authoritative access-grant snapshot for SSE replay."""
        payload = await self._projection("access-grants.snapshot")
        sequence = _integer(payload, "sequence")
        if query.after_sequence is not None and sequence < query.after_sequence:
            raise IamUnavailableError("access-grant projection replay moved backwards")
        generated_at = _datetime(payload.get("generated_at"), "generated_at")
        raw_requests = payload.get("requests", [])
        if not isinstance(raw_requests, list):
            raise IamUnavailableError("access-grant projection requests are malformed")
        return AccessGrantSnapshot(
            sequence=sequence,
            generated_at=generated_at,
            requests=tuple(_access_grant(item) for item in raw_requests[: query.limit]),
        )

    async def decide(self, command: AccessGrantDecisionCommand) -> AccessGrantDecisionResult:
        """Persist a revision-fenced access decision without applying permission."""
        await self._proposal("access-grants.decide", command, command.request_id)
        return AccessGrantDecisionResult(
            request_id=command.request_id,
            status="pending",
            revision=command.expected_revision,
            approved_count=0,
            quorum=1,
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
        return {
            **payload,
            "can_manage_web_search": can_manage_web_search,
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
    return AccessGrantRecord(
        request_id=str(value.get("request_id") or ""),
        correlation_id=str(value.get("correlation_id") or ""),
        capability_id=str(value.get("capability_id") or ""),
        scope_ref=str(value.get("scope_ref") or ""),
        grant_mode=str(value.get("grant_mode") or ""),
        requested_at=_datetime(value.get("requested_at"), "requested_at"),
        expires_at=_datetime(value.get("expires_at"), "expires_at"),
        quorum=int(value.get("quorum", 0)),
        status=str(value.get("status") or ""),
        revision=int(value.get("revision", 0)),
    )


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
