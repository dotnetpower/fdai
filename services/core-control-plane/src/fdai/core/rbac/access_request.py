"""Governed human-access requests backed by tracked state and audit.

This module records requests to add or remove a human from one of the FDAI
Entra role groups. It never calls Microsoft Graph and never changes group
membership. An Owner applies an approved request through the tenant's identity
administration process after the independent approval gate clears.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, Role, has_capability
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX: Final[str] = "rbac:access-request:"
_DECISION_PREFIX: Final[str] = "rbac:access-request-decision:"
_DEFAULT_MIN_JUSTIFICATION_CHARS: Final[int] = 20
_MAX_IDENTIFIER_CHARS: Final[int] = 256
_MAX_JUSTIFICATION_CHARS: Final[int] = 2_000


class AccessOperation(StrEnum):
    """Supported access-membership changes."""

    GRANT = "grant"
    REVOKE = "revoke"
    SET = "set"


class AccessRequestStatus(StrEnum):
    """Lifecycle state visible in the read-only IAM projection."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AccessReviewDecision(StrEnum):
    """Terminal Owner review decision for an access request."""

    APPROVE = "approve"
    REJECT = "reject"


class AccessRequestError(ValueError):
    """Base class for rejected access-request input."""


class AccessRequestConflictError(AccessRequestError):
    """An idempotency key was reused for a different request intent."""


class AccessRequestPermissionError(PermissionError):
    """The principal lacks the capability required by the operation."""


@dataclass(frozen=True, slots=True)
class AccessRequest:
    """One immutable request to grant or revoke a human App Role."""

    request_id: str
    idempotency_key: str
    requester_oid: str
    identity_provider: str
    target_subject_id: str
    target_username: str
    operation: AccessOperation
    role: Role
    justification: str
    requested_at: datetime
    status: AccessRequestStatus = AccessRequestStatus.PENDING
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_justification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "requester_oid": self.requester_oid,
            "identity_provider": self.identity_provider,
            "target_subject_id": self.target_subject_id,
            "target_username": self.target_username,
            "operation": self.operation.value,
            "role": self.role.value,
            "justification": self.justification,
            "requested_at": self.requested_at.isoformat(),
            "status": self.status.value,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_justification": self.review_justification,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccessRequest:
        return cls(
            request_id=_required_string(value, "request_id"),
            idempotency_key=_required_string(value, "idempotency_key"),
            requester_oid=_required_string(value, "requester_oid"),
            identity_provider=str(value.get("identity_provider") or "entra"),
            target_subject_id=_required_subject_id(value),
            target_username=_required_string(value, "target_username"),
            operation=AccessOperation(_required_string(value, "operation")),
            role=Role(_required_string(value, "role")),
            justification=_required_string(value, "justification"),
            requested_at=datetime.fromisoformat(_required_string(value, "requested_at")),
            status=AccessRequestStatus(_required_string(value, "status")),
            reviewed_by=_optional_stored_string(value, "reviewed_by"),
            reviewed_at=_optional_datetime(value, "reviewed_at"),
            review_justification=_optional_stored_string(value, "review_justification"),
        )


@dataclass(frozen=True, slots=True)
class AccessRequestService:
    """Validate, persist, audit, and project human-access requests."""

    store: StateStore
    min_justification_chars: int = _DEFAULT_MIN_JUSTIFICATION_CHARS

    def __post_init__(self) -> None:
        if self.min_justification_chars < 1:
            raise ValueError("min_justification_chars MUST be >= 1")

    async def submit(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        identity_provider: str,
        target_subject_id: str,
        target_username: str,
        operation: AccessOperation,
        role: Role,
        justification: str,
        self_service: bool = False,
        now: datetime | None = None,
    ) -> AccessRequest:
        """Create or replay one immutable access request."""

        if self_service:
            if principal.roles:
                raise AccessRequestPermissionError(
                    "self-service access requests are only available to unassigned principals"
                )
            if operation is not AccessOperation.GRANT or role is not Role.READER:
                raise AccessRequestPermissionError(
                    "self-service access requests may only grant the Reader role"
                )
            if target_subject_id.strip() != principal.oid.strip():
                raise AccessRequestPermissionError(
                    "self-service access requests MUST target the authenticated principal"
                )
        elif not has_capability(principal.roles, Capability.AUTHOR_DRAFT_PR):
            raise AccessRequestPermissionError("author-draft-pr capability is required")
        requester_oid = _bounded(principal.oid, "principal oid")
        normalized_key = _bounded(idempotency_key, "idempotency_key")
        normalized_provider = _bounded(identity_provider, "identity_provider").casefold()
        normalized_subject_id = _bounded(target_subject_id, "target_subject_id")
        normalized_username = _bounded(target_username, "target_username")
        normalized_justification = justification.strip()
        if len(normalized_justification) < self.min_justification_chars:
            raise AccessRequestError(
                f"justification MUST be at least {self.min_justification_chars} characters"
            )
        if len(normalized_justification) > _MAX_JUSTIFICATION_CHARS:
            raise AccessRequestError(
                f"justification MUST be at most {_MAX_JUSTIFICATION_CHARS} characters"
            )
        if role is Role.BREAK_GLASS:
            raise AccessRequestError("BreakGlass is not available through routine access requests")

        state_key = _state_key(requester_oid, normalized_key)
        requested_at = now or datetime.now(UTC)
        if requested_at.tzinfo is None:
            raise AccessRequestError("requested_at MUST be timezone-aware")
        request = AccessRequest(
            request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, state_key)),
            idempotency_key=normalized_key,
            requester_oid=requester_oid,
            identity_provider=normalized_provider,
            target_subject_id=normalized_subject_id,
            target_username=normalized_username,
            operation=operation,
            role=role,
            justification=normalized_justification,
            requested_at=requested_at.astimezone(UTC),
        )

        existing = await self.store.read_state(state_key)
        if existing is not None:
            return _same_or_conflict(existing, request)
        audit_entry = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": request.request_id,
            "actor": requester_oid,
            "action_kind": "iam.access-requested",
            "mode": "shadow",
            "decision": "pending",
            "idempotency_key": normalized_key,
            "identity_provider": normalized_provider,
            "target_subject_id": normalized_subject_id,
            "operation": operation.value,
            "role": role.value,
            "timestamp": request.requested_at.isoformat(),
        }
        created = await self.store.write_state_with_audit_if_absent(
            state_key,
            request.to_dict(),
            audit_entry,
        )
        if not created:
            raced = await self.store.read_state(state_key)
            if raced is None:
                raise RuntimeError("access request lost after an atomic create race")
            return _same_or_conflict(raced, request)

        return request

    async def list_requests(
        self,
        *,
        principal: Principal,
        limit: int = 50,
    ) -> tuple[AccessRequest, ...]:
        """Return requests visible to the principal, newest-first."""

        requests, _ = await self.list_request_page(principal=principal, limit=limit)
        return requests

    async def list_request_page(
        self,
        *,
        principal: Principal,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[AccessRequest, ...], int]:
        """Return one principal-scoped request page and the stable total."""

        if limit < 1 or limit > 200:
            raise AccessRequestError("limit MUST be between 1 and 200")
        if offset < 0:
            raise AccessRequestError("offset MUST be >= 0")
        manager = has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP)
        rows, total = await self.store.read_state_page(
            _STATE_PREFIX,
            limit=limit,
            offset=offset,
            field=None if manager else "requester_oid",
            value=None if manager else principal.oid,
        )
        projected: list[AccessRequest] = []
        for row in rows:
            projected.append(await self._with_decision(AccessRequest.from_dict(dict(row))))
        return tuple(projected), total

    async def review(
        self,
        *,
        principal: Principal,
        request_id: str,
        decision: AccessReviewDecision,
        justification: str,
        now: datetime | None = None,
    ) -> AccessRequest:
        """Record an Owner review without changing provider membership."""

        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            raise AccessRequestPermissionError("manage-group-membership capability is required")
        normalized_request_id = _bounded(request_id, "request_id")
        normalized_justification = justification.strip()
        if len(normalized_justification) < self.min_justification_chars:
            raise AccessRequestError(
                f"justification MUST be at least {self.min_justification_chars} characters"
            )
        request = await self._find_request(normalized_request_id)
        if request is None:
            raise AccessRequestError("access request was not found")
        # Case-insensitive: an object id is the same principal however it is
        # cased, so a raw comparison would let a requester approve their own
        # request by presenting a differently-cased id.
        if request.requester_oid.strip().casefold() == principal.oid.strip().casefold():
            raise AccessRequestPermissionError("requester MUST NOT approve their own request")
        reviewed_at = now or datetime.now(UTC)
        if reviewed_at.tzinfo is None:
            raise AccessRequestError("reviewed_at MUST be timezone-aware")
        payload = {
            "request_id": normalized_request_id,
            "decision": decision.value,
            "reviewed_by": principal.oid,
            "reviewed_at": reviewed_at.astimezone(UTC).isoformat(),
            "justification": normalized_justification,
        }
        decision_key = f"{_DECISION_PREFIX}{normalized_request_id}"
        audit_entry = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": normalized_request_id,
            "actor": principal.oid,
            "action_kind": "iam.access-reviewed",
            "mode": "shadow",
            "decision": decision.value,
            "idempotency_key": normalized_request_id,
            "target_subject_id": request.target_subject_id,
            "identity_provider": request.identity_provider,
            "timestamp": reviewed_at.astimezone(UTC).isoformat(),
        }
        created = await self.store.write_state_with_audit_if_absent(
            decision_key,
            payload,
            audit_entry,
        )
        if not created:
            existing = await self.store.read_state(decision_key)
            if existing is None or not _same_review(existing, payload):
                raise AccessRequestConflictError("access request already has a decision")
        return await self._with_decision(request)

    async def _find_request(self, request_id: str) -> AccessRequest | None:
        row = await self.store.find_state(
            _STATE_PREFIX,
            field="request_id",
            value=request_id,
        )
        return None if row is None else AccessRequest.from_dict(dict(row))

    async def _with_decision(self, request: AccessRequest) -> AccessRequest:
        decision = await self.store.read_state(f"{_DECISION_PREFIX}{request.request_id}")
        if decision is None:
            return request
        raw_decision = _required_string(dict(decision), "decision")
        status = (
            AccessRequestStatus.APPROVED
            if raw_decision == AccessReviewDecision.APPROVE.value
            else AccessRequestStatus.REJECTED
        )
        return replace(
            request,
            status=status,
            reviewed_by=_required_string(dict(decision), "reviewed_by"),
            reviewed_at=datetime.fromisoformat(_required_string(dict(decision), "reviewed_at")),
            review_justification=_required_string(dict(decision), "justification"),
        )


def _state_key(requester_oid: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{requester_oid}\x00{idempotency_key}".encode()).hexdigest()
    return f"{_STATE_PREFIX}{digest}"


def _same_or_conflict(existing: Any, requested: AccessRequest) -> AccessRequest:
    if not isinstance(existing, dict):
        raise RuntimeError("stored access request is not a JSON object")
    current = AccessRequest.from_dict(existing)
    comparable = (
        "requester_oid",
        "identity_provider",
        "target_subject_id",
        "target_username",
        "operation",
        "role",
        "justification",
    )
    if any(getattr(current, field) != getattr(requested, field) for field in comparable):
        raise AccessRequestConflictError("idempotency key payload conflict")
    return current


def _bounded(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AccessRequestError(f"{name} MUST be a non-empty string")
    if len(normalized) > _MAX_IDENTIFIER_CHARS:
        raise AccessRequestError(f"{name} MUST be at most {_MAX_IDENTIFIER_CHARS} characters")
    return normalized


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"stored access request {key} is invalid")
    return item


def _required_subject_id(value: dict[str, Any]) -> str:
    item = value.get("target_subject_id", value.get("target_oid"))
    if not isinstance(item, str) or not item:
        raise RuntimeError("stored access request target_subject_id is invalid")
    return item


def _optional_stored_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) and item else None


def _optional_datetime(value: dict[str, Any], key: str) -> datetime | None:
    item = _optional_stored_string(value, key)
    return datetime.fromisoformat(item) if item else None


def _same_review(existing: Any, requested: dict[str, str]) -> bool:
    if not isinstance(existing, dict):
        return False
    return all(
        existing.get(field) == requested[field]
        for field in ("request_id", "decision", "reviewed_by", "justification")
    )


__all__ = [
    "AccessOperation",
    "AccessRequest",
    "AccessRequestConflictError",
    "AccessRequestError",
    "AccessRequestPermissionError",
    "AccessRequestService",
    "AccessRequestStatus",
    "AccessReviewDecision",
]
