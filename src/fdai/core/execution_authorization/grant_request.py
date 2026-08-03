"""Audited lifecycle for bounded execution-identity access grants."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.shared.providers.execution_authorization import ExecutionAccessGrantProposal
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "execution-authorization:grant-request:"
_MAX_DECISION_CAS_ATTEMPTS = 4
_MAX_PROJECTION_SCAN = 1_000


class AccessGrantRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    VERIFIED = "verified"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AccessGrantDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class AccessGrantRequestError(ValueError):
    pass


class AccessGrantRequestConflictError(AccessGrantRequestError):
    pass


class AccessGrantRequestPermissionError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class AccessGrantRequest:
    request_id: str
    idempotency_key: str
    original_action_id: str
    authorization_decision_digest: str
    requirement_id: str
    capability_id: str
    execution_profile: str
    executor_identity_ref: str
    scope_ref: str
    grant_mode: str
    mapping_digest: str
    plan_digest: str
    requester_ref: str
    requested_at: datetime
    expires_at: datetime
    quorum: int
    approver_roles: frozenset[str]
    status: AccessGrantRequestStatus = AccessGrantRequestStatus.PENDING
    revision: int = 0
    reviewed_by: str | None = None
    approved_by: tuple[str, ...] = ()
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    apply_receipt_ref: str | None = None
    applied_by: str | None = None
    applied_at: datetime | None = None
    observation_digest: str | None = None
    verified_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        required = (
            self.request_id,
            self.idempotency_key,
            self.original_action_id,
            self.authorization_decision_digest,
            self.requirement_id,
            self.capability_id,
            self.execution_profile,
            self.executor_identity_ref,
            self.scope_ref,
            self.grant_mode,
            self.mapping_digest,
            self.plan_digest,
            self.requester_ref,
        )
        if any(not value.strip() for value in required):
            raise AccessGrantRequestError("access grant request fields MUST be non-empty")
        if not self.scope_ref.startswith("scope://"):
            raise AccessGrantRequestError("access grant scope MUST use a scope:// reference")
        if self.requested_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise AccessGrantRequestError("access grant timestamps MUST be timezone-aware")
        if self.expires_at <= self.requested_at:
            raise AccessGrantRequestError("access grant expiry MUST follow request time")
        if self.quorum < 1 or not self.approver_roles:
            raise AccessGrantRequestError("access grant approval policy MUST be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.__dict_without_slots(),
            "approver_roles": sorted(self.approver_roles),
            "status": self.status.value,
            "requested_at": self.requested_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

    def __dict_without_slots(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccessGrantRequest:
        timestamps = (
            "requested_at",
            "expires_at",
            "reviewed_at",
            "applied_at",
            "verified_at",
            "revoked_at",
        )
        normalized = dict(value)
        for key in timestamps:
            raw = normalized.get(key)
            normalized[key] = datetime.fromisoformat(raw) if isinstance(raw, str) else None
        normalized["status"] = AccessGrantRequestStatus(str(value["status"]))
        normalized["approver_roles"] = frozenset(value["approver_roles"])
        normalized["approved_by"] = tuple(value.get("approved_by", ()))
        return cls(**normalized)


@dataclass(frozen=True, slots=True)
class AccessGrantRequestService:
    store: StateStore

    async def list_pending_for_roles(
        self,
        *,
        reviewer_ref: str,
        reviewer_roles: frozenset[str],
        now: datetime,
        limit: int = 50,
    ) -> tuple[AccessGrantRequest, ...]:
        if not reviewer_ref.strip():
            raise AccessGrantRequestError("access grant reviewer reference MUST be non-empty")
        if now.tzinfo is None:
            raise AccessGrantRequestError("access grant projection time MUST be timezone-aware")
        if not 1 <= limit <= 100:
            raise AccessGrantRequestError("access grant projection limit MUST be between 1 and 100")
        normalized_roles = {role.casefold() for role in reviewer_roles}
        if not normalized_roles:
            return ()
        values = await self.store.read_states(_STATE_PREFIX, limit=_MAX_PROJECTION_SCAN)
        visible: list[AccessGrantRequest] = []
        for value in values:
            request = AccessGrantRequest.from_dict(dict(value))
            if request.status is not AccessGrantRequestStatus.PENDING:
                continue
            if request.expires_at <= now:
                continue
            if request.requester_ref.casefold() == reviewer_ref.casefold():
                continue
            if not normalized_roles.intersection(
                role.casefold() for role in request.approver_roles
            ):
                continue
            visible.append(request)
            if len(visible) == limit:
                break
        return tuple(visible)

    async def submit_grant(self, proposal: ExecutionAccessGrantProposal) -> str:
        request = await self.submit(
            idempotency_key=proposal.idempotency_key,
            original_action_id=proposal.original_action_id,
            authorization_decision_digest=proposal.authorization_decision_digest,
            requirement_id=proposal.requirement_id,
            capability_id=proposal.capability_id,
            execution_profile=proposal.execution_profile,
            executor_identity_ref=proposal.executor_identity_ref,
            scope_ref=proposal.scope_ref,
            grant_mode=proposal.grant_mode,
            mapping_digest=proposal.mapping_digest,
            plan_digest=proposal.plan_digest,
            requester_ref=proposal.requester_ref,
            requested_at=proposal.requested_at,
            expires_at=proposal.expires_at,
            quorum=proposal.quorum,
            approver_roles=proposal.approver_roles,
        )
        return request.request_id

    async def submit(
        self,
        *,
        idempotency_key: str,
        original_action_id: str,
        authorization_decision_digest: str,
        requirement_id: str,
        capability_id: str,
        execution_profile: str,
        executor_identity_ref: str,
        scope_ref: str,
        grant_mode: str,
        mapping_digest: str,
        plan_digest: str,
        requester_ref: str,
        requested_at: datetime,
        expires_at: datetime,
        quorum: int,
        approver_roles: frozenset[str],
    ) -> AccessGrantRequest:
        request_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                ":".join(
                    (
                        original_action_id,
                        authorization_decision_digest,
                        idempotency_key,
                        requirement_id,
                        scope_ref,
                        mapping_digest,
                    )
                ),
            )
        )
        request = AccessGrantRequest(
            request_id=request_id,
            idempotency_key=idempotency_key,
            original_action_id=original_action_id,
            authorization_decision_digest=authorization_decision_digest,
            requirement_id=requirement_id,
            capability_id=capability_id,
            execution_profile=execution_profile,
            executor_identity_ref=executor_identity_ref,
            scope_ref=scope_ref,
            grant_mode=grant_mode,
            mapping_digest=mapping_digest,
            plan_digest=plan_digest,
            requester_ref=requester_ref,
            requested_at=requested_at,
            expires_at=expires_at,
            quorum=quorum,
            approver_roles=approver_roles,
        )
        key = _state_key(request_id)
        existing = await self.store.read_state(key)
        if existing is not None:
            replay = AccessGrantRequest.from_dict(dict(existing))
            if _intent_digest(replay) != _intent_digest(request):
                raise AccessGrantRequestConflictError(
                    "access grant idempotency key is bound to a different intent"
                )
            return replay
        created = await self.store.write_state_with_audit_if_absent(
            key,
            request.to_dict(),
            _audit(
                request,
                "iam.executor-grant-requested",
                "pending",
                requested_at,
                actor=requester_ref,
            ),
        )
        if created:
            return request
        raced = await self.store.read_state(key)
        if raced is None:
            raise AccessGrantRequestConflictError("access grant request creation raced")
        replay = AccessGrantRequest.from_dict(dict(raced))
        if _intent_digest(replay) != _intent_digest(request):
            raise AccessGrantRequestConflictError(
                "access grant idempotency key is bound to a different intent"
            )
        return replay

    async def decide(
        self,
        *,
        request_id: str,
        reviewer_ref: str,
        reviewer_roles: frozenset[str],
        decision: AccessGrantDecision,
        reason: str,
        decided_at: datetime,
        expected_revision: int | None = None,
    ) -> AccessGrantRequest:
        if expected_revision is not None and expected_revision < 0:
            raise AccessGrantRequestError("access grant expected revision MUST be non-negative")
        for _attempt in range(_MAX_DECISION_CAS_ATTEMPTS):
            try:
                return await self._decide_once(
                    request_id=request_id,
                    reviewer_ref=reviewer_ref,
                    reviewer_roles=reviewer_roles,
                    decision=decision,
                    reason=reason,
                    decided_at=decided_at,
                    expected_revision=expected_revision,
                )
            except AccessGrantRequestConflictError as exc:
                if "revision changed" not in str(exc):
                    raise
        raise AccessGrantRequestConflictError(
            "access grant request revision changed after bounded retries"
        )

    async def _decide_once(
        self,
        *,
        request_id: str,
        reviewer_ref: str,
        reviewer_roles: frozenset[str],
        decision: AccessGrantDecision,
        reason: str,
        decided_at: datetime,
        expected_revision: int | None,
    ) -> AccessGrantRequest:
        request = await self._load(request_id)
        if expected_revision is not None and request.revision != expected_revision:
            raise AccessGrantRequestConflictError("access grant request revision changed")
        if request.status is not AccessGrantRequestStatus.PENDING:
            raise AccessGrantRequestConflictError("access grant request is not pending")
        if reviewer_ref.casefold() == request.requester_ref.casefold():
            raise AccessGrantRequestPermissionError("access grant requests cannot be self-approved")
        normalized_reviewer_roles = {role.casefold() for role in reviewer_roles}
        if not normalized_reviewer_roles.intersection(
            role.casefold() for role in request.approver_roles
        ):
            raise AccessGrantRequestPermissionError("reviewer lacks an approved access-grant role")
        if not reason.strip():
            raise AccessGrantRequestError("access grant review reason MUST be non-empty")
        if decided_at >= request.expires_at:
            raise AccessGrantRequestConflictError("access grant request expired before review")
        normalized_reviewer = reviewer_ref.casefold()
        prior_approvers = {item.casefold() for item in request.approved_by}
        if decision is AccessGrantDecision.APPROVE and normalized_reviewer in prior_approvers:
            raise AccessGrantRequestConflictError("reviewer already approved this grant request")
        approved_by = request.approved_by
        if decision is AccessGrantDecision.APPROVE:
            approved_by = tuple(sorted((*approved_by, reviewer_ref), key=str.casefold))
        approved = len(approved_by) >= request.quorum
        updated = replace(
            request,
            status=(
                AccessGrantRequestStatus.REJECTED
                if decision is AccessGrantDecision.REJECT
                else AccessGrantRequestStatus.APPROVED
                if approved
                else AccessGrantRequestStatus.PENDING
            ),
            revision=request.revision + 1,
            reviewed_by=reviewer_ref,
            approved_by=approved_by,
            reviewed_at=decided_at,
            review_reason=reason.strip(),
        )
        return await self._transition(
            request,
            updated,
            "iam.executor-grant-decided",
            decision.value,
            decided_at,
            actor=reviewer_ref,
        )

    async def record_apply(
        self,
        *,
        request_id: str,
        deployer_ref: str,
        plan_digest: str,
        receipt_ref: str,
        applied_at: datetime,
    ) -> AccessGrantRequest:
        request = await self._load(request_id)
        if request.status is not AccessGrantRequestStatus.APPROVED:
            raise AccessGrantRequestConflictError("access grant request is not approved")
        if plan_digest != request.plan_digest:
            raise AccessGrantRequestConflictError("access grant apply plan digest changed")
        if deployer_ref.casefold() == request.executor_identity_ref.casefold():
            raise AccessGrantRequestPermissionError("executor identity cannot apply its own grant")
        updated = replace(
            request,
            status=AccessGrantRequestStatus.APPLIED,
            revision=request.revision + 1,
            apply_receipt_ref=receipt_ref,
            applied_by=deployer_ref,
            applied_at=applied_at,
        )
        return await self._transition(
            request,
            updated,
            "iam.executor-grant-applied",
            "applied",
            applied_at,
            actor=deployer_ref,
        )

    async def verify(
        self,
        *,
        request_id: str,
        observation_digest: str,
        verifier_ref: str,
        verified_at: datetime,
    ) -> AccessGrantRequest:
        request = await self._load(request_id)
        if request.status is not AccessGrantRequestStatus.APPLIED:
            raise AccessGrantRequestConflictError("access grant request is not applied")
        if verified_at >= request.expires_at:
            raise AccessGrantRequestConflictError("access grant expired before verification")
        if not observation_digest.strip():
            raise AccessGrantRequestError("access grant observation digest MUST be non-empty")
        updated = replace(
            request,
            status=AccessGrantRequestStatus.VERIFIED,
            revision=request.revision + 1,
            observation_digest=observation_digest,
            verified_at=verified_at,
        )
        return await self._transition(
            request,
            updated,
            "iam.executor-grant-verified",
            "verified",
            verified_at,
            actor=verifier_ref,
        )

    async def revoke(
        self,
        *,
        request_id: str,
        revoked_by: str,
        revoked_at: datetime,
    ) -> AccessGrantRequest:
        request = await self._load(request_id)
        if request.status not in {
            AccessGrantRequestStatus.APPLIED,
            AccessGrantRequestStatus.VERIFIED,
        }:
            raise AccessGrantRequestConflictError("access grant request is not active")
        updated = replace(
            request,
            status=AccessGrantRequestStatus.REVOKED,
            revision=request.revision + 1,
            revoked_at=revoked_at,
        )
        return await self._transition(
            request,
            updated,
            "iam.executor-grant-revoked",
            "revoked",
            revoked_at,
            actor=revoked_by,
        )

    async def expire(self, *, request_id: str, now: datetime) -> AccessGrantRequest:
        request = await self._load(request_id)
        if now < request.expires_at:
            raise AccessGrantRequestConflictError("access grant request has not expired")
        if request.status in {
            AccessGrantRequestStatus.REJECTED,
            AccessGrantRequestStatus.REVOKED,
            AccessGrantRequestStatus.EXPIRED,
        }:
            return request
        updated = replace(
            request,
            status=AccessGrantRequestStatus.EXPIRED,
            revision=request.revision + 1,
        )
        return await self._transition(
            request,
            updated,
            "iam.executor-grant-expired",
            "expired",
            now,
            actor="fdai.system.expiry",
        )

    async def _load(self, request_id: str) -> AccessGrantRequest:
        value = await self.store.read_state(_state_key(request_id))
        if value is None:
            raise AccessGrantRequestError("access grant request was not found")
        return AccessGrantRequest.from_dict(dict(value))

    async def _transition(
        self,
        current: AccessGrantRequest,
        updated: AccessGrantRequest,
        action_kind: str,
        decision: str,
        timestamp: datetime,
        *,
        actor: str,
    ) -> AccessGrantRequest:
        changed = await self.store.compare_and_set_state_with_audit(
            _state_key(current.request_id),
            updated.to_dict(),
            expected_revision=current.revision,
            audit_entry=_audit(updated, action_kind, decision, timestamp, actor=actor),
        )
        if not changed:
            raise AccessGrantRequestConflictError("access grant request revision changed")
        return updated


def _state_key(request_id: str) -> str:
    return f"{_STATE_PREFIX}{request_id}"


def _intent_digest(request: AccessGrantRequest) -> str:
    fields = (
        request.original_action_id,
        request.authorization_decision_digest,
        request.requirement_id,
        request.capability_id,
        request.execution_profile,
        request.executor_identity_ref,
        request.scope_ref,
        request.grant_mode,
        request.mapping_digest,
        request.plan_digest,
        request.expires_at.isoformat(),
    )
    return hashlib.sha256("\0".join(fields).encode("utf-8")).hexdigest()


def _audit(
    request: AccessGrantRequest,
    action_kind: str,
    decision: str,
    timestamp: datetime,
    *,
    actor: str,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "correlation_id": request.request_id,
        "idempotency_key": request.idempotency_key,
        "actor": actor,
        "action_kind": action_kind,
        "mode": "shadow",
        "decision": decision,
        "request_id": request.request_id,
        "authorization_decision_digest": request.authorization_decision_digest,
        "requirement_id": request.requirement_id,
        "capability_id": request.capability_id,
        "execution_profile": request.execution_profile,
        "executor_identity_ref": request.executor_identity_ref,
        "grant_mode": request.grant_mode,
        "scope_ref": request.scope_ref,
        "plan_digest": request.plan_digest,
        "revision": request.revision,
        "timestamp": timestamp.astimezone(UTC).isoformat(),
    }


__all__ = [
    "AccessGrantDecision",
    "AccessGrantRequest",
    "AccessGrantRequestConflictError",
    "AccessGrantRequestError",
    "AccessGrantRequestPermissionError",
    "AccessGrantRequestService",
    "AccessGrantRequestStatus",
]
