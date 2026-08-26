"""Govern authorized operator guidance and exact-target Incident intake exceptions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fdai_service_contracts.incident_intervention import (
    IncidentInterventionAction as RequestAction,
)
from fdai_service_contracts.incident_intervention import (
    IncidentInterventionRequest,
    incident_target_ref,
)
from fdai_service_contracts.operator import OperatorRole

from fdai.shared.contracts.models import Incident, IncidentState
from fdai.shared.providers.state_store import StateStore

from .lifecycle import IncidentOperatorPrincipal, IncidentWorkflowForbiddenError
from .registry import IncidentRegistry

MAX_INTERVENTION_COMMENT_CHARS = 500
PERMANENT_EXCEPTION_REVIEW_DAYS = 30
_EXCEPTION_KEY_PREFIX = "incident-intake-exception:"
_SUPPRESSION_KEY_PREFIX = "incident-intake-suppression:"
_INTERVENTION_KEY_PREFIX = "incident-intervention:"


class IncidentExceptionDuration(StrEnum):
    """Server-owned duration choices exposed by the Operator request contract."""

    ONE_DAY = "one_day"
    ONE_WEEK = "one_week"
    ONE_MONTH = "one_month"
    UNTIL_REVOKED = "until_revoked"


@dataclass(frozen=True, slots=True)
class IncidentIntakeException:
    """One exact-target intake exception that never suppresses findings or audit."""

    exception_id: UUID
    target_ref: str
    justification: str
    created_by: str
    created_at: datetime
    duration: IncidentExceptionDuration
    expires_at: datetime | None
    review_at: datetime | None
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, "created_at")
        if not self.target_ref.strip() or len(self.target_ref) > 1024:
            raise ValueError(
                "incident intake exception target_ref must contain 1 to 1024 characters"
            )
        _validated_comment(self.justification)
        if not self.created_by.strip():
            raise ValueError("incident intake exception created_by must be non-empty")
        if self.duration is IncidentExceptionDuration.UNTIL_REVOKED:
            if self.expires_at is not None or self.review_at is None:
                raise ValueError("until-revoked exception requires review_at and no expires_at")
        elif self.expires_at is None or self.review_at is not None:
            raise ValueError("bounded exception requires expires_at and no review_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.created_at:
                raise ValueError("incident intake exception expires_at must follow created_at")
        if self.review_at is not None:
            _require_aware(self.review_at, "review_at")
            if self.review_at <= self.created_at:
                raise ValueError("incident intake exception review_at must follow created_at")
        if (self.revoked_at is None) is not (self.revoked_by is None):
            raise ValueError("incident intake exception revocation metadata must be complete")
        if self.revoked_at is not None:
            _require_aware(self.revoked_at, "revoked_at")
            if self.revoked_at < self.created_at or not (self.revoked_by or "").strip():
                raise ValueError("incident intake exception revocation is invalid")

    def active_at(self, moment: datetime) -> bool:
        """Return whether this exception suppresses intake at one aware UTC moment."""
        _require_aware(moment, "moment")
        return self.revoked_at is None and (self.expires_at is None or moment < self.expires_at)


class IncidentIntakeExceptionRegistry:
    """Resolve exact-target exceptions without granting rule or execution authority."""

    def __init__(self) -> None:
        self._exceptions: dict[UUID, IncidentIntakeException] = {}

    def create(
        self,
        *,
        target_ref: str,
        justification: str,
        duration: IncidentExceptionDuration,
        principal: IncidentOperatorPrincipal,
        now: datetime | None = None,
        exception_id: UUID | None = None,
    ) -> IncidentIntakeException:
        """Create one exception after enforcing its duration-specific role floor."""
        _require_role(
            principal,
            "owner" if duration is IncidentExceptionDuration.UNTIL_REVOKED else "approver",
        )
        moment = now or datetime.now(tz=UTC)
        _require_aware(moment, "now")
        expires_at = None
        review_at = None
        if duration is IncidentExceptionDuration.UNTIL_REVOKED:
            review_at = moment + timedelta(days=PERMANENT_EXCEPTION_REVIEW_DAYS)
        else:
            days = {
                IncidentExceptionDuration.ONE_DAY: 1,
                IncidentExceptionDuration.ONE_WEEK: 7,
                IncidentExceptionDuration.ONE_MONTH: 30,
            }[duration]
            expires_at = moment + timedelta(days=days)
        created = IncidentIntakeException(
            exception_id=exception_id or uuid4(),
            target_ref=target_ref.strip(),
            justification=_validated_comment(justification),
            created_by=principal.id,
            created_at=moment,
            duration=duration,
            expires_at=expires_at,
            review_at=review_at,
        )
        if created.exception_id in self._exceptions:
            if self._exceptions[created.exception_id] != created:
                raise ValueError("incident intake exception id conflicts with another request")
            return self._exceptions[created.exception_id]
        self._exceptions[created.exception_id] = created
        return created

    def revoke(
        self,
        exception_id: UUID,
        *,
        principal: IncidentOperatorPrincipal,
        now: datetime | None = None,
    ) -> IncidentIntakeException:
        """Revoke one exception without reopening any previously closed Incident."""
        _require_role(principal, "approver")
        existing = self._exceptions.get(exception_id)
        if existing is None:
            raise KeyError(f"unknown incident intake exception: {exception_id}")
        if existing.revoked_at is not None:
            return existing
        moment = now or datetime.now(tz=UTC)
        _require_aware(moment, "now")
        revoked = replace(existing, revoked_at=moment, revoked_by=principal.id)
        self._exceptions[exception_id] = revoked
        return revoked

    def active_for(
        self,
        target_ref: str,
        *,
        now: datetime | None = None,
    ) -> IncidentIntakeException | None:
        """Return the newest active exception for the exact normalized target."""
        target = target_ref.strip()
        moment = now or datetime.now(tz=UTC)
        _require_aware(moment, "now")
        matches = [
            item
            for item in self._exceptions.values()
            if item.target_ref == target and item.active_at(moment)
        ]
        return max(
            matches,
            key=lambda item: (item.created_at, str(item.exception_id)),
            default=None,
        )

    def snapshot(self) -> Mapping[UUID, IncidentIntakeException]:
        """Return an immutable current snapshot for projection and replay tests."""
        return MappingProxyType(dict(self._exceptions))


class StateStoreIncidentIntakeExceptionRegistry:
    """Persist current exact-target exceptions and append every lifecycle audit."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def create(
        self,
        *,
        target_ref: str,
        justification: str,
        duration: IncidentExceptionDuration,
        principal: IncidentOperatorPrincipal,
        now: datetime,
        exception_id: UUID,
    ) -> IncidentIntakeException:
        """Atomically create or replace an inactive exact-target exception."""
        candidate = IncidentIntakeExceptionRegistry().create(
            target_ref=target_ref,
            justification=justification,
            duration=duration,
            principal=principal,
            now=now,
            exception_id=exception_id,
        )
        key = _exception_key(candidate.target_ref)
        current = await self._state_store.read_state(key)
        if current is None:
            created = await self._state_store.write_state_with_audit_if_absent(
                key,
                _serialize_exception(candidate, revision=1),
                _exception_audit(candidate, kind="incident.intake-exception-created"),
            )
            if created:
                return candidate
            current = await self._state_store.read_state(key)
        if current is None:
            raise RuntimeError("incident intake exception state disappeared after create race")
        existing, revision = _deserialize_exception(current)
        if existing.exception_id == candidate.exception_id:
            if existing != candidate:
                raise ValueError("incident intake exception id conflicts with another request")
            return existing
        if existing.active_at(now):
            raise ValueError("an active incident intake exception already exists for this target")
        replaced = await self._state_store.compare_and_set_state_with_audit(
            key,
            _serialize_exception(candidate, revision=revision + 1),
            expected_revision=revision,
            audit_entry=_exception_audit(candidate, kind="incident.intake-exception-created"),
        )
        if not replaced:
            raise RuntimeError("incident intake exception changed concurrently")
        return candidate

    async def revoke(
        self,
        exception_id: UUID,
        *,
        target_ref: str,
        principal: IncidentOperatorPrincipal,
        now: datetime,
    ) -> IncidentIntakeException:
        """Atomically revoke the current exception for one exact target."""
        _require_role(principal, "approver")
        key = _exception_key(target_ref)
        current = await self._state_store.read_state(key)
        if current is None:
            raise KeyError(f"unknown incident intake exception: {exception_id}")
        existing, revision = _deserialize_exception(current)
        if existing.exception_id != exception_id:
            raise KeyError(f"unknown incident intake exception: {exception_id}")
        if existing.revoked_at is not None:
            return existing
        revoked = replace(existing, revoked_at=now, revoked_by=principal.id)
        updated = await self._state_store.compare_and_set_state_with_audit(
            key,
            _serialize_exception(revoked, revision=revision + 1),
            expected_revision=revision,
            audit_entry=_exception_audit(revoked, kind="incident.intake-exception-revoked"),
        )
        if not updated:
            latest = await self._state_store.read_state(key)
            if latest is not None:
                latest_exception, _ = _deserialize_exception(latest)
                if latest_exception.exception_id == exception_id and latest_exception.revoked_at:
                    return latest_exception
            raise RuntimeError("incident intake exception changed concurrently")
        return revoked

    async def active_for(
        self,
        target_ref: str,
        *,
        now: datetime,
    ) -> IncidentIntakeException | None:
        """Read one exact-target current exception and apply expiry locally."""
        current = await self._state_store.read_state(_exception_key(target_ref))
        if current is None:
            return None
        exception, _ = _deserialize_exception(current)
        return exception if exception.active_at(now) else None

    async def record_suppression(
        self,
        *,
        exception: IncidentIntakeException,
        correlation_id: str,
        evidence_keys: tuple[str, ...],
        event_type: str,
        occurred_at: datetime,
    ) -> bool:
        """Append one replay-safe finding receipt without creating an Incident."""
        _require_aware(occurred_at, "occurred_at")
        evidence_digest = hashlib.sha256("\0".join(sorted(evidence_keys)).encode()).hexdigest()
        occurred_at_value = occurred_at.astimezone(UTC).isoformat()
        suppression_id = hashlib.sha256(
            (
                f"{exception.exception_id}\0{correlation_id}\0{event_type}\0"
                f"{evidence_digest}\0{occurred_at_value}"
            ).encode()
        ).hexdigest()
        review_overdue = exception.review_at is not None and occurred_at >= exception.review_at
        state = {
            "schema_version": "1.0.0",
            "suppression_id": suppression_id,
            "exception_id": str(exception.exception_id),
            "target_ref": exception.target_ref,
            "correlation_id": correlation_id,
            "evidence_digest": f"sha256:{evidence_digest}",
            "occurred_at": occurred_at_value,
            "exception_review_overdue": review_overdue,
        }
        return await self._state_store.write_state_with_audit_if_absent(
            f"{_SUPPRESSION_KEY_PREFIX}{suppression_id}",
            state,
            {
                "kind": "finding.incident-intake-suppressed",
                "idempotency_key": f"incident-intake-suppressed::{suppression_id}",
                "correlation_id": correlation_id,
                "exception_id": str(exception.exception_id),
                "target_ref": exception.target_ref,
                "event_type": event_type,
                "evidence_digest": f"sha256:{evidence_digest}",
                "actor_oid": exception.created_by,
                "at": occurred_at_value,
                "reason": exception.justification,
                "incident_created": False,
                "exception_review_overdue": review_overdue,
            },
        )


@dataclass(frozen=True, slots=True)
class _RequestPrincipal:
    id: str
    role: str


class IncidentInterventionService:
    """Apply validated Operator requests through Core-owned Incident authority."""

    def __init__(
        self,
        *,
        registry: IncidentRegistry,
        exceptions: StateStoreIncidentIntakeExceptionRegistry,
        state_store: StateStore,
    ) -> None:
        self._registry = registry
        self._exceptions = exceptions
        self._state_store = state_store

    async def apply(self, request: IncidentInterventionRequest) -> None:
        """Apply once, resume only request-owned closure progress, and audit completion."""

        if await self._is_completed(request):
            return
        incident_id = UUID(request.incident_id)
        incident = self._registry.get(incident_id)
        if incident is None:
            raise KeyError(f"unknown incident intervention incident: {incident_id}")
        if _incident_target(incident) != request.target_ref:
            raise ValueError("incident intervention target no longer matches")
        principal = _request_principal(request)
        result_ref: str | None = None
        if request.action is RequestAction.GUIDANCE:
            if incident.state.value != request.expected_state:
                raise ValueError("incident intervention expected state is stale")
        elif request.action is RequestAction.CLOSE_AS_DEVELOPMENT:
            await self._close_as_development(request, incident, principal)
        elif request.action is RequestAction.CREATE_DEVELOPMENT_EXCEPTION:
            if incident.state.value != request.expected_state:
                raise ValueError("incident intervention expected state is stale")
            if request.duration is None:
                raise ValueError("incident exception duration is missing")
            created = await self._exceptions.create(
                target_ref=request.target_ref,
                justification=request.comment,
                duration=IncidentExceptionDuration(request.duration.value),
                principal=principal,
                now=request.requested_at,
                exception_id=uuid5(
                    NAMESPACE_URL,
                    f"fdai.incident-exception://{request.request_id}",
                ),
            )
            result_ref = str(created.exception_id)
        elif request.action is RequestAction.REVOKE_DEVELOPMENT_EXCEPTION:
            if incident.state.value != request.expected_state:
                raise ValueError("incident intervention expected state is stale")
            if request.exception_id is None:
                raise ValueError("incident exception id is missing")
            revoked = await self._exceptions.revoke(
                UUID(request.exception_id),
                target_ref=request.target_ref,
                principal=principal,
                now=request.requested_at,
            )
            result_ref = str(revoked.exception_id)
        else:
            raise ValueError("unsupported incident intervention action")
        await self._record_completion(request, result_ref=result_ref)

    async def _close_as_development(
        self,
        request: IncidentInterventionRequest,
        incident: Incident,
        principal: _RequestPrincipal,
    ) -> None:
        path = _development_closure_path(IncidentState(request.expected_state))
        try:
            current_index = path.index(incident.state)
        except ValueError as exc:
            raise ValueError("incident intervention expected state is stale") from exc
        if current_index > 0 and not await self._closure_prefix_is_request_owned(
            request,
            path[: current_index + 1],
        ):
            raise ValueError("incident intervention closure progress is not request-owned")
        reason = _development_closure_reason(request)
        for target in path[current_index + 1 :]:
            await self._registry.transition(
                incident_id=incident.incident_id,
                to_state=target,
                actor_oid=principal.id,
                reason=reason,
                at=request.requested_at,
            )

    async def _closure_prefix_is_request_owned(
        self,
        request: IncidentInterventionRequest,
        prefix: tuple[IncidentState, ...],
    ) -> bool:
        expected = {
            (source.value, target.value) for source, target in zip(prefix, prefix[1:], strict=False)
        }
        if not expected:
            return True
        matched: set[tuple[str, str]] = set()
        for row in await self._state_store.read_incident_transitions():
            edge = (str(row.get("from_state") or ""), str(row.get("to_state") or ""))
            if (
                row.get("kind") == "incident.transition"
                and row.get("incident_id") == request.incident_id
                and row.get("actor_oid") == request.principal_id
                and row.get("at") == request.requested_at.isoformat()
                and row.get("reason") == _development_closure_reason(request)
                and edge in expected
            ):
                matched.add(edge)
        return matched == expected

    async def _is_completed(self, request: IncidentInterventionRequest) -> bool:
        current = await self._state_store.read_state(_intervention_key(request.request_id))
        if current is None:
            return False
        if current.get("request_digest") != request.request_digest:
            raise ValueError("incident intervention request id conflicts with another payload")
        return True

    async def _record_completion(
        self,
        request: IncidentInterventionRequest,
        *,
        result_ref: str | None,
    ) -> None:
        state = {
            "schema_version": "1.0.0",
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "incident_id": request.incident_id,
            "correlation_id": request.correlation_id,
            "target_ref": request.target_ref,
            "action": request.action.value,
            "principal_id": request.principal_id,
            "comment": request.comment,
            "result_ref": result_ref,
            "applied_at": request.requested_at.isoformat(),
        }
        created = await self._state_store.write_state_with_audit_if_absent(
            _intervention_key(request.request_id),
            state,
            {
                "kind": "incident.intervention-applied",
                "idempotency_key": f"incident-intervention::{request.request_id}",
                **state,
                "actor_oid": request.principal_id,
                "accountable_agent": "Saga",
                "execution_authority": False,
            },
        )
        if not created and not await self._is_completed(request):
            raise RuntimeError("incident intervention completion changed concurrently")


def _request_principal(request: IncidentInterventionRequest) -> _RequestPrincipal:
    rank = {
        OperatorRole.READER: 0,
        OperatorRole.CONTRIBUTOR: 1,
        OperatorRole.APPROVER: 2,
        OperatorRole.OWNER: 3,
        OperatorRole.BREAK_GLASS: -1,
    }
    role = max(request.principal_roles, key=rank.__getitem__)
    return _RequestPrincipal(id=request.principal_id, role=role.value)


def _incident_target(incident: Incident) -> str:
    resources = tuple(
        key.removeprefix("resource:")
        for key in incident.correlation_keys
        if key.startswith("resource:") and key.removeprefix("resource:")
    )
    if len(resources) != 1:
        raise ValueError("incident does not have one exact resource target")
    return incident_target_ref(resources[0])


def _development_closure_path(initial: IncidentState) -> tuple[IncidentState, ...]:
    return {
        IncidentState.OPEN: (
            IncidentState.OPEN,
            IncidentState.TRIAGING,
            IncidentState.RESOLVED,
            IncidentState.CLOSED,
        ),
        IncidentState.TRIAGING: (
            IncidentState.TRIAGING,
            IncidentState.RESOLVED,
            IncidentState.CLOSED,
        ),
        IncidentState.MITIGATED: (
            IncidentState.MITIGATED,
            IncidentState.RESOLVED,
            IncidentState.CLOSED,
        ),
        IncidentState.RESOLVED: (IncidentState.RESOLVED, IncidentState.CLOSED),
        IncidentState.CLOSED: (IncidentState.CLOSED,),
    }[initial]


def _development_closure_reason(request: IncidentInterventionRequest) -> str:
    return f"development closure [{request.request_id}]: {request.comment}"


def _intervention_key(request_id: str) -> str:
    return f"{_INTERVENTION_KEY_PREFIX}{hashlib.sha256(request_id.encode()).hexdigest()}"


def _validated_comment(comment: str) -> str:
    normalized = comment.strip()
    if not 1 <= len(normalized) <= MAX_INTERVENTION_COMMENT_CHARS:
        raise ValueError(
            "incident intervention comment must contain 1 to "
            f"{MAX_INTERVENTION_COMMENT_CHARS} characters"
        )
    return normalized


def _exception_key(target_ref: str) -> str:
    target = target_ref.strip()
    if not target:
        raise ValueError("incident intake exception target_ref must be non-empty")
    return f"{_EXCEPTION_KEY_PREFIX}{hashlib.sha256(target.encode()).hexdigest()}"


def _serialize_exception(
    exception: IncidentIntakeException,
    *,
    revision: int,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "exception_id": str(exception.exception_id),
        "target_ref": exception.target_ref,
        "justification": exception.justification,
        "created_by": exception.created_by,
        "created_at": exception.created_at.isoformat(),
        "duration": exception.duration.value,
        "expires_at": exception.expires_at.isoformat() if exception.expires_at else None,
        "review_at": exception.review_at.isoformat() if exception.review_at else None,
        "revoked_at": exception.revoked_at.isoformat() if exception.revoked_at else None,
        "revoked_by": exception.revoked_by,
    }


def _deserialize_exception(
    value: Mapping[str, object],
) -> tuple[IncidentIntakeException, int]:
    try:
        raw_revision = value["revision"]
        if not isinstance(raw_revision, int) or isinstance(raw_revision, bool):
            raise TypeError("revision must be an integer")
        revision = raw_revision
        exception = IncidentIntakeException(
            exception_id=UUID(str(value["exception_id"])),
            target_ref=str(value["target_ref"]),
            justification=str(value["justification"]),
            created_by=str(value["created_by"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            duration=IncidentExceptionDuration(str(value["duration"])),
            expires_at=_optional_datetime(value.get("expires_at")),
            review_at=_optional_datetime(value.get("review_at")),
            revoked_at=_optional_datetime(value.get("revoked_at")),
            revoked_by=str(value["revoked_by"]) if value.get("revoked_by") else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("stored incident intake exception is malformed") from exc
    if revision < 1:
        raise RuntimeError("stored incident intake exception revision is invalid")
    return exception, revision


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _exception_audit(
    exception: IncidentIntakeException,
    *,
    kind: str,
) -> dict[str, object]:
    occurred_at = exception.revoked_at or exception.created_at
    actor = exception.revoked_by or exception.created_by
    return {
        "kind": kind,
        "idempotency_key": f"{exception.exception_id}::{kind}",
        "exception_id": str(exception.exception_id),
        "target_ref": exception.target_ref,
        "duration": exception.duration.value,
        "expires_at": exception.expires_at.isoformat() if exception.expires_at else None,
        "review_at": exception.review_at.isoformat() if exception.review_at else None,
        "actor_oid": actor,
        "at": occurred_at.isoformat(),
        "reason": exception.justification,
        "incident_created": False,
    }


def _require_role(principal: IncidentOperatorPrincipal, minimum: str) -> None:
    ranks = {"reader": 0, "contributor": 1, "approver": 2, "owner": 3}
    role = str(getattr(principal.role, "value", principal.role)).casefold()
    if ranks.get(role, -1) < ranks[minimum]:
        raise IncidentWorkflowForbiddenError(
            f"incident intervention requires role>={minimum}; principal role={role}"
        )


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"incident intake exception {field} must be timezone-aware")


__all__ = [
    "IncidentExceptionDuration",
    "IncidentIntakeException",
    "IncidentIntakeExceptionRegistry",
    "MAX_INTERVENTION_COMMENT_CHARS",
    "PERMANENT_EXCEPTION_REVIEW_DAYS",
    "StateStoreIncidentIntakeExceptionRegistry",
]
