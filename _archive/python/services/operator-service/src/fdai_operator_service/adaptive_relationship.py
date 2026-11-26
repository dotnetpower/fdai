"""Read-only verification of current human-to-agent conversation relationships.

Responsibility:
    Join the current ownership projection with independent directory observations.
Boundary:
    Accept only a server-authenticated principal and an already selected agent.
Authority and state:
    Return an expiring presentation proof or explicit unknown; never grant access,
    change the selected agent, or write ownership, membership, or workflow state.
Dependencies:
    Existing Operations ProjectionReader and HumanIdentityDirectory ports.
Deployment:
    Runs inside Operator without importing Core or invoking an interview workflow.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast, get_args
from uuid import uuid4

from fdai_service_contracts import OperatorRole
from fdai_service_contracts.adaptive_answer import AdaptiveAgentName
from fdai_service_contracts.adaptive_relationship import AdaptiveRelationshipProof

from fdai_operator_service.families.iam.contracts import (
    DirectoryIdentity,
    HumanIdentityDirectory,
    HumanIdentityDirectoryStatus,
)
from fdai_operator_service.families.operations.contracts import ProjectionQuery, ProjectionReader

_LOGGER = logging.getLogger(__name__)
_AGENTS = frozenset(get_args(AdaptiveAgentName))
_DUTIES = frozenset({"primary", "backup", "escalation"})
_RelationshipKind = Literal["steward", "collaborator"]


@dataclass(frozen=True, slots=True)
class AdaptiveRelationshipPolicy:
    """Bound directory freshness, proof lifetime, and total read work."""

    timeout_seconds: float = 5.0
    max_source_age_seconds: float = 300.0
    proof_ttl_seconds: float = 60.0
    max_subjects: int = 64
    max_groups: int = 4
    roster_limit: int = 500

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.timeout_seconds, 30),
            (self.max_source_age_seconds, 3_600),
            (self.proof_ttl_seconds, 300),
            (self.max_subjects, 64),
            (self.max_groups, 8),
            (self.roster_limit, 500),
        ):
            if isinstance(value, bool) or not 0 < value <= maximum:
                raise ValueError("adaptive relationship limits MUST be positive and bounded")
        if any(
            type(value) is not int
            for value in (self.max_subjects, self.max_groups, self.roster_limit)
        ):
            raise ValueError("adaptive relationship count limits MUST be integers")


@dataclass(frozen=True, slots=True)
class AdaptiveRelationshipResolution:
    """A fixed-target proof or content-free reason why the relationship is unknown."""

    target_agent: AdaptiveAgentName
    status: Literal["matched", "unknown"]
    reason: str | None
    proof: AdaptiveRelationshipProof | None

    def __post_init__(self) -> None:
        if self.status == "matched":
            if self.proof is None or self.reason is not None:
                raise ValueError("matched relationship requires exactly one proof")
            if self.proof.target_agent != self.target_agent:
                raise ValueError("relationship proof cannot change the selected agent")
        elif self.status != "unknown" or self.proof is not None or not self.reason:
            raise ValueError("unknown relationship requires a reason and no proof")


class _UnknownRelationshipError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AdaptiveRelationshipResolver:
    """Verify one current mapping without using names, UI claims, or role inference.

    ``roles`` are passed unchanged to the projection's existing authorization
    boundary. They are never interpreted as group membership or stewardship.
    """

    ownership: ProjectionReader
    directory: HumanIdentityDirectory
    clock: Callable[[], datetime] = _utc_now
    policy: AdaptiveRelationshipPolicy = AdaptiveRelationshipPolicy()

    async def resolve(
        self,
        *,
        principal_id: str,
        roles: frozenset[OperatorRole],
        target_agent: AdaptiveAgentName,
    ) -> AdaptiveRelationshipResolution:
        """Return an immutable expiring proof, or unknown after bounded failure.

        The caller supplies the authenticated subject and already authorized
        explicit/durable target. External cancellation propagates; no provider
        request is retried by this resolver.
        """

        if target_agent not in _AGENTS:
            raise ValueError("adaptive relationship target MUST be a fixed Pantheon agent")
        try:
            if (
                not _bounded_identifier(principal_id)
                or not isinstance(roles, frozenset)
                or any(not isinstance(role, OperatorRole) for role in roles)
            ):
                raise _UnknownRelationshipError("invalid_principal_context")
            async with asyncio.timeout(self.policy.timeout_seconds):
                proof = await self._verify(principal_id, roles, target_agent)
            return AdaptiveRelationshipResolution(target_agent, "matched", None, proof)
        except asyncio.CancelledError:
            raise
        except _UnknownRelationshipError as exc:
            reason = exc.reason
        except TimeoutError:
            reason = "relationship_deadline"
        except (RuntimeError, ValueError, TypeError, OSError):
            reason = "relationship_source_unavailable"
        _LOGGER.info(
            "adaptive_relationship_unknown", extra={"target_agent": target_agent, "reason": reason}
        )
        return AdaptiveRelationshipResolution(target_agent, "unknown", reason, None)

    async def _verify(
        self, principal_id: str, roles: frozenset[OperatorRole], target_agent: AdaptiveAgentName
    ) -> AdaptiveRelationshipProof:
        started = _aware(self.clock(), "clock_unavailable")
        payload = await self.ownership.read(
            ProjectionQuery(
                operation="stewardship.coverage",
                principal_id=principal_id,
                path={},
                params={},
                limit=len(_AGENTS),
                cursor=None,
                roles=roles,
                purpose="operations-review",
            )
        )
        current = _mapping(payload.get("current_ownership"), "ownership_unavailable")
        if current.get("authority") != "read_only":
            raise _UnknownRelationshipError("ownership_unavailable")
        revision = current.get("source_revision")
        if not _bounded_identifier(revision) or str(revision).casefold() in {
            "unversioned",
            "unknown",
            "unavailable",
        }:
            raise _UnknownRelationshipError("ownership_unversioned")
        if payload.get("_revision") is not None and payload["_revision"] != revision:
            raise _UnknownRelationshipError("ownership_revision_mismatch")
        now = _aware(self.clock(), "clock_unavailable")
        expiry = min(
            started + timedelta(seconds=self.policy.proof_ttl_seconds),
            self._fresh_until(current.get("directory"), now, "ownership_directory_stale"),
        )
        agents = _rows(current.get("agents"), len(_AGENTS), "ownership_invalid")
        selected = [agent for agent in agents if agent.get("name") == target_agent]
        if len(selected) != 1:
            reason = "mapping_ambiguous" if selected else "mapping_not_found"
            raise _UnknownRelationshipError(reason)
        agent = selected[0]
        coverage = agent.get("coverage")
        if isinstance(coverage, Mapping) and coverage.get("status") == "identity_review":
            raise _UnknownRelationshipError("ownership_stale")
        expiry = _scope_expiry(agent.get("scope"), now, expiry)
        health = current.get("identity_health")
        if isinstance(health, Mapping) and health.get("availability") == "available":
            expiry = min(expiry, _aware(health.get("expires_at"), "ownership_stale"))
        subjects = _rows(agent.get("subjects"), self.policy.max_subjects, "mapping_invalid")
        keys = [(item.get("kind"), item.get("subject_id")) for item in subjects]
        if any(not _bounded_identifier(subject_id) for _, subject_id in keys):
            raise _UnknownRelationshipError("mapping_invalid")
        if len(set(keys)) != len(keys):
            raise _UnknownRelationshipError("mapping_ambiguous")
        if sum(kind == "group" for kind, _ in keys) > self.policy.max_groups:
            raise _UnknownRelationshipError("mapping_limit_exceeded")
        identity = await self.directory.get_by_subject_id(principal_id)
        if (
            identity is None
            or identity.subject_id != principal_id
            or identity.principal_type != "person"
        ):
            raise _UnknownRelationshipError("principal_not_verified")
        if identity.active is not True:
            raise _UnknownRelationshipError("principal_inactive")
        kinds: set[_RelationshipKind] = set()
        for subject in subjects:
            subject_kind = subject.get("kind")
            if subject_kind not in {"user", "group"}:
                raise _UnknownRelationshipError("mapping_invalid")
            if subject_kind == "user" and subject["subject_id"] != principal_id:
                continue
            kind = _relationship_kind(subject)
            if subject_kind == "user" or await self._group_member(
                cast(str, subject["subject_id"]), identity
            ):
                kinds.add(kind)
        if len(kinds) != 1:
            raise _UnknownRelationshipError("mapping_ambiguous" if kinds else "mapping_not_found")
        if not isinstance(self.directory, HumanIdentityDirectoryStatus):
            raise _UnknownRelationshipError("directory_freshness_unavailable")
        status = await self.directory.directory_status()
        finished = _aware(self.clock(), "clock_unavailable")
        expiry = min(expiry, self._fresh_until(status.to_dict(), finished, "directory_stale"))
        if finished < started or expiry <= finished:
            raise _UnknownRelationshipError("relationship_expired")
        return AdaptiveRelationshipProof(
            target_agent=target_agent,
            principal_id=principal_id,
            kind=next(iter(kinds)),
            source_revision=cast(str, revision),
            verified_at=finished,
            expires_at=expiry,
        )

    def _fresh_until(self, value: object, now: datetime, reason: str) -> datetime:
        state = _mapping(value, reason)
        if state.get("availability") != "available":
            raise _UnknownRelationshipError(reason)
        observed = _aware(state.get("observed_at"), reason)
        expiry = observed + timedelta(seconds=self.policy.max_source_age_seconds)
        if observed > now or expiry <= now:
            raise _UnknownRelationshipError(reason)
        return expiry

    async def _group_member(self, group_id: str, principal: DirectoryIdentity) -> bool:
        """Require an exact echoed query marker, never an existing App Role.

        Some directories serve an application roster instead of the requested
        group. A fresh non-authority marker prevents that unrelated roster from
        masquerading as membership evidence, even if subjects share App Roles.
        """

        marker = f"adaptive_relationship_{uuid4().hex}"
        roster = await self.directory.list_role_roster(
            {marker: group_id}, limit=self.policy.roster_limit
        )
        if len(roster) > self.policy.roster_limit:
            raise _UnknownRelationshipError("group_membership_unavailable")
        groups = [
            item
            for item in roster
            if item.subject_id == group_id
            and item.principal_type == "group"
            and marker in item.roles
        ]
        if len(groups) != 1 or groups[0].active is not True:
            raise _UnknownRelationshipError("group_membership_unavailable")
        members = [
            item
            for item in roster
            if item.subject_id == principal.subject_id and item.principal_type == "person"
        ]
        if not members:
            if len(roster) >= self.policy.roster_limit:
                raise _UnknownRelationshipError("group_membership_unavailable")
            return False
        if (
            len(members) != 1
            or members[0].active is not True
            or members[0].provider != principal.provider
            or marker not in members[0].roles
        ):
            raise _UnknownRelationshipError("group_membership_unavailable")
        return True


def _relationship_kind(subject: Mapping[str, object]) -> _RelationshipKind:
    if subject.get("active") is not True:
        raise _UnknownRelationshipError("mapping_inactive")
    if subject.get("resolution") != "resolved":
        raise _UnknownRelationshipError("mapping_unavailable")
    responsibility, duty = subject.get("responsibility"), subject.get("duty")
    if responsibility == "accountable" and duty in _DUTIES:
        return "steward"
    if responsibility == "informed" and duty is None:
        return "collaborator"
    raise _UnknownRelationshipError("mapping_invalid")


def _bounded_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 256
        and value.isascii()
        and all(32 < ord(character) < 127 for character in value)
    )


def _mapping(value: object, reason: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _UnknownRelationshipError(reason)
    return value


def _rows(value: object, maximum: int, reason: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > maximum:
        raise _UnknownRelationshipError(reason)
    return tuple(_mapping(item, reason) for item in value)


def _aware(value: object, reason: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise _UnknownRelationshipError(reason) from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _UnknownRelationshipError(reason)
    return value.astimezone(UTC)


def _scope_expiry(value: object, now: datetime, expiry: datetime) -> datetime:
    if value is None:
        return expiry
    scope = _mapping(value, "ownership_stale")
    if scope.get("effective_from") is not None:
        if _aware(scope["effective_from"], "ownership_stale") > now:
            raise _UnknownRelationshipError("ownership_stale")
    if scope.get("effective_until") is not None:
        expiry = min(expiry, _aware(scope["effective_until"], "ownership_stale"))
    if expiry <= now:
        raise _UnknownRelationshipError("ownership_stale")
    return expiry


__all__ = [
    "AdaptiveRelationshipPolicy",
    "AdaptiveRelationshipResolution",
    "AdaptiveRelationshipResolver",
]
