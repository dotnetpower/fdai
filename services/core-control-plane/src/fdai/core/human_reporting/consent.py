"""Requester consent records for contacting a report-line approval route."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from fdai.core.human_reporting.model import (
    ReportingLineModelError,
    normalize_principal,
    reporting_instant,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "human_reporting:approval-consent:"


class ApprovalContactConsentExpiredError(ReportingLineModelError):
    """Raised when a requester answers after the contact-consent deadline."""


class ApprovalContactConsentState(StrEnum):
    """Lifecycle state for permission to contact one exact approval route."""

    PENDING = "pending"
    CONSENTED = "consented"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class ApprovalContactConsent:
    """One short-lived consent that never represents action approval."""

    consent_id: str
    requester_ref: str
    action_digest: str
    route_digest: str
    path_revision: str
    created_at: datetime
    expires_at: datetime
    state: ApprovalContactConsentState = ApprovalContactConsentState.PENDING
    revision: int = 0
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "requester_ref", normalize_principal(self.requester_ref))
        for value, name in (
            (self.action_digest, "action_digest"),
            (self.route_digest, "route_digest"),
            (self.path_revision, "path_revision"),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ReportingLineModelError(f"{name} MUST be a lowercase SHA-256")
        object.__setattr__(self, "created_at", reporting_instant(self.created_at))
        object.__setattr__(self, "expires_at", reporting_instant(self.expires_at))
        if self.created_at >= self.expires_at:
            raise ReportingLineModelError("approval contact consent window MUST be non-empty")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ReportingLineModelError("approval contact consent revision MUST be non-negative")
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at", reporting_instant(self.decided_at))
        if (self.state is ApprovalContactConsentState.PENDING) != (self.decided_at is None):
            raise ReportingLineModelError("approval contact consent decision time is inconsistent")

    @property
    def digest(self) -> str:
        value = {
            "consent_id": self.consent_id,
            "requester_ref": self.requester_ref,
            "action_digest": self.action_digest,
            "route_digest": self.route_digest,
            "path_revision": self.path_revision,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "consent_id": self.consent_id,
            "requester_ref": self.requester_ref,
            "action_digest": self.action_digest,
            "route_digest": self.route_digest,
            "path_revision": self.path_revision,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "state": self.state.value,
            "revision": self.revision,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "consent_digest": self.digest,
            "approval_authority": False,
            "execution_authority": False,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ApprovalContactConsent:
        try:
            created_at = datetime.fromisoformat(str(value["created_at"]))
            expires_at = datetime.fromisoformat(str(value["expires_at"]))
            decided_at = (
                datetime.fromisoformat(str(value["decided_at"]))
                if value.get("decided_at") is not None
                else None
            )
            revision = value["revision"]
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise TypeError("consent revision is not an integer")
            consent = cls(
                consent_id=str(value["consent_id"]),
                requester_ref=str(value["requester_ref"]),
                action_digest=str(value["action_digest"]),
                route_digest=str(value["route_digest"]),
                path_revision=str(value["path_revision"]),
                created_at=created_at,
                expires_at=expires_at,
                state=ApprovalContactConsentState(str(value["state"])),
                revision=revision,
                decided_at=decided_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportingLineModelError("approval contact consent record is malformed") from exc
        if value.get("schema_version") != "1.0.0" or value.get("consent_digest") != consent.digest:
            raise ReportingLineModelError("approval contact consent integrity is invalid")
        if (
            value.get("approval_authority") is not False
            or value.get("execution_authority") is not False
        ):
            raise ReportingLineModelError("approval contact consent cannot carry authority")
        return consent


@dataclass(frozen=True, slots=True)
class ApprovalContactConsentService:
    """Create and decide short-lived contact consent with atomic audit writes."""

    store: StateStore
    ttl: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not timedelta(seconds=30) <= self.ttl <= timedelta(minutes=10):
            raise ValueError("approval contact consent TTL MUST be in [30 seconds, 10 minutes]")

    async def request(
        self,
        *,
        requester_ref: str,
        action_digest: str,
        route_digest: str,
        path_revision: str,
        now: datetime | None = None,
    ) -> ApprovalContactConsent:
        """Create or replay consent for one exact action and route."""

        created_at = reporting_instant(now or datetime.now(tz=UTC))
        requester = normalize_principal(requester_ref)
        identity = f"{requester}:{action_digest}:{route_digest}:{path_revision}"
        consent_id = str(uuid5(NAMESPACE_URL, "fdai:report-line-consent:" + identity))
        requested = ApprovalContactConsent(
            consent_id=consent_id,
            requester_ref=requester,
            action_digest=action_digest,
            route_digest=route_digest,
            path_revision=path_revision,
            created_at=created_at,
            expires_at=created_at + self.ttl,
        )
        key = _PREFIX + consent_id
        created = await self.store.write_state_with_audit_if_absent(
            key,
            requested.to_dict(),
            {
                "actor": requester,
                "action_kind": "human.reporting.approval_contact_consent_requested",
                "consent_id": consent_id,
                "consent_digest": requested.digest,
                "recorded_at": created_at.isoformat(),
                "mode": "shadow",
                "approval_authority": False,
                "execution_authority": False,
            },
        )
        if created:
            return requested
        existing = await self.get(consent_id)
        if (
            existing.requester_ref != requester
            or existing.action_digest != action_digest
            or existing.route_digest != route_digest
            or existing.path_revision != path_revision
        ):
            raise ReportingLineModelError("approval contact consent id conflicts")
        return existing

    async def decide(
        self,
        *,
        consent_id: str,
        requester_ref: str,
        consent: bool,
        expected_revision: int,
        now: datetime | None = None,
    ) -> ApprovalContactConsent:
        """Record the requester's notification decision, never an action decision."""

        current = await self.get(consent_id)
        actor = normalize_principal(requester_ref)
        decided_at = reporting_instant(now or datetime.now(tz=UTC))
        if current.requester_ref != actor:
            raise PermissionError("only the requester may decide approval contact consent")
        if current.state is not ApprovalContactConsentState.PENDING:
            desired = (
                ApprovalContactConsentState.CONSENTED
                if consent
                else ApprovalContactConsentState.DECLINED
            )
            if current.state is desired:
                return current
            raise ReportingLineModelError("approval contact consent is already decided")
        if current.revision != expected_revision:
            raise ReportingLineModelError("approval contact consent revision is stale")
        if decided_at >= current.expires_at:
            raise ApprovalContactConsentExpiredError("approval contact consent has expired")
        candidate = replace(
            current,
            state=(
                ApprovalContactConsentState.CONSENTED
                if consent
                else ApprovalContactConsentState.DECLINED
            ),
            revision=current.revision + 1,
            decided_at=decided_at,
        )
        applied = await self.store.compare_and_set_state_with_audit(
            _PREFIX + consent_id,
            candidate.to_dict(),
            expected_revision=current.revision,
            audit_entry={
                "actor": actor,
                "action_kind": "human.reporting.approval_contact_consent_decided",
                "consent_id": consent_id,
                "consent_digest": candidate.digest,
                "decision": candidate.state.value,
                "recorded_at": decided_at.isoformat(),
                "mode": "shadow",
                "approval_authority": False,
                "execution_authority": False,
            },
        )
        if not applied:
            raise ReportingLineModelError("approval contact consent revision changed")
        return candidate

    async def get(self, consent_id: str) -> ApprovalContactConsent:
        value = await self.store.read_state(_PREFIX + consent_id)
        if value is None:
            raise ReportingLineModelError("approval contact consent was not found")
        return ApprovalContactConsent.from_dict(dict(value))


__all__ = [
    "ApprovalContactConsent",
    "ApprovalContactConsentExpiredError",
    "ApprovalContactConsentService",
    "ApprovalContactConsentState",
]
