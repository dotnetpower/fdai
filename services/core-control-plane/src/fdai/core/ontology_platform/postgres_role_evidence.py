"""Project typed PostgreSQL role observations without exposing raw principals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

_MAX_FRESHNESS_SECONDS = 31_536_000


class PostgresRoleProjectionReason(StrEnum):
    """Stable terminal reason for one database-role evidence projection."""

    PROJECTED = "projected"
    WRONG_SCOPE = "wrong_scope"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class PostgresRoleObservation:
    """One authenticated database-catalog observation of a service role."""

    observation_id: str
    role_name: str
    service_ref: str
    scope_ref: str
    can_login: bool
    superuser: bool
    create_database: bool
    create_role: bool
    inherit: bool
    replication: bool
    bypass_row_level_security: bool
    observed_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int
    source_identity: str
    source_revision: str
    evidence_ref: str
    authentication_ref: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for field_name, text_value in (
            ("observation_id", self.observation_id),
            ("role_name", self.role_name),
            ("service_ref", self.service_ref),
            ("scope_ref", self.scope_ref),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("evidence_ref", self.evidence_ref),
            ("authentication_ref", self.authentication_ref),
        ):
            if not text_value.strip() or len(text_value) > 512:
                raise ValueError(
                    f"PostgresRoleObservation.{field_name} MUST be bounded non-empty text"
                )
        for field_name, reference in (
            ("evidence_ref", self.evidence_ref),
            ("authentication_ref", self.authentication_ref),
        ):
            if not _is_digest(reference):
                raise ValueError(f"PostgresRoleObservation.{field_name} MUST be canonical SHA-256")
        for field_name, flag_value in (
            ("can_login", self.can_login),
            ("superuser", self.superuser),
            ("create_database", self.create_database),
            ("create_role", self.create_role),
            ("inherit", self.inherit),
            ("replication", self.replication),
            ("bypass_row_level_security", self.bypass_row_level_security),
        ):
            if not isinstance(flag_value, bool):
                raise ValueError(f"PostgresRoleObservation.{field_name} MUST be boolean")
        for field_name, timestamp in (
            ("observed_at", self.observed_at),
            ("evidence_cutoff", self.evidence_cutoff),
            ("recorded_at", self.recorded_at),
        ):
            if timestamp.tzinfo is None:
                raise ValueError(f"PostgresRoleObservation.{field_name} MUST be timezone-aware")
        if self.observed_at > self.evidence_cutoff or self.evidence_cutoff > self.recorded_at:
            raise ValueError("PostgreSQL role observation timestamps MUST be ordered")
        if isinstance(self.freshness_ceiling_seconds, bool) or not isinstance(
            self.freshness_ceiling_seconds, int
        ):
            raise ValueError("PostgreSQL role freshness ceiling MUST be an integer")
        if not 1 <= self.freshness_ceiling_seconds <= _MAX_FRESHNESS_SECONDS:
            raise ValueError("PostgreSQL role freshness ceiling exceeds its bound")
        if self.execution_authority or self.mutation_authority:
            raise ValueError("PostgreSQL role observation MUST NOT carry action authority")


@dataclass(frozen=True, slots=True)
class PostgresRoleEvidence:
    """Principal-safe database-role attributes with replay provenance."""

    service_ref: str
    principal_handle: str
    can_login: bool
    superuser: bool
    create_database: bool
    create_role: bool
    inherit: bool
    replication: bool
    bypass_row_level_security: bool
    observed_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int
    source_identity: str
    source_revision: str
    evidence_refs: tuple[str, ...]
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False


@dataclass(frozen=True, slots=True)
class PostgresRoleProjection:
    """One principal-safe role result or fail-closed reason."""

    reason: PostgresRoleProjectionReason
    evidence: PostgresRoleEvidence | None
    digest: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        projected = self.reason is PostgresRoleProjectionReason.PROJECTED
        if projected != (self.evidence is not None):
            raise ValueError("PostgreSQL role projected reason MUST match evidence presence")


def project_postgres_role_evidence(
    observation: PostgresRoleObservation,
    *,
    principal_scope_ref: str,
    readable_service_refs: Collection[str],
    evaluation_time: datetime,
) -> PostgresRoleProjection:
    """Return sanitized role evidence only within the principal's exact scope."""

    if not principal_scope_ref.strip() or len(principal_scope_ref) > 512:
        raise ValueError("PostgreSQL role principal_scope_ref MUST be bounded non-empty text")
    if evaluation_time.tzinfo is None:
        raise ValueError("PostgreSQL role evaluation_time MUST be timezone-aware")
    if evaluation_time < observation.recorded_at:
        raise ValueError("PostgreSQL role evaluation_time MUST NOT precede recorded_at")
    readable = frozenset(readable_service_refs)
    context = {
        "evaluation_time": _timestamp(evaluation_time),
        "principal_scope_ref": principal_scope_ref,
        "readable_services_digest": _digest(sorted(readable)),
    }
    if observation.scope_ref != principal_scope_ref or observation.service_ref not in readable:
        return _projection(
            observation,
            reason=PostgresRoleProjectionReason.WRONG_SCOPE,
            context=context,
        )
    if (
        evaluation_time - observation.evidence_cutoff
    ).total_seconds() > observation.freshness_ceiling_seconds:
        return _projection(
            observation,
            reason=PostgresRoleProjectionReason.STALE,
            context=context,
        )
    evidence = PostgresRoleEvidence(
        service_ref=observation.service_ref,
        principal_handle=_digest(
            {
                "role_name": observation.role_name,
                "service_ref": observation.service_ref,
                "scope_ref": observation.scope_ref,
                "source_identity": observation.source_identity,
            }
        ),
        can_login=observation.can_login,
        superuser=observation.superuser,
        create_database=observation.create_database,
        create_role=observation.create_role,
        inherit=observation.inherit,
        replication=observation.replication,
        bypass_row_level_security=observation.bypass_row_level_security,
        observed_at=observation.observed_at,
        evidence_cutoff=observation.evidence_cutoff,
        recorded_at=observation.recorded_at,
        freshness_ceiling_seconds=observation.freshness_ceiling_seconds,
        source_identity=observation.source_identity,
        source_revision=observation.source_revision,
        evidence_refs=tuple(sorted((observation.authentication_ref, observation.evidence_ref))),
    )
    return _projection(
        observation,
        reason=PostgresRoleProjectionReason.PROJECTED,
        context=context,
        evidence=evidence,
    )


def _projection(
    observation: PostgresRoleObservation,
    *,
    reason: PostgresRoleProjectionReason,
    context: dict[str, str],
    evidence: PostgresRoleEvidence | None = None,
) -> PostgresRoleProjection:
    body = {
        "context": context,
        "observation_digest": _digest(_observation_body(observation)),
        "projected_evidence": _evidence_body(evidence),
        "reason": reason.value,
    }
    return PostgresRoleProjection(reason=reason, evidence=evidence, digest=_digest(body))


def _observation_body(observation: PostgresRoleObservation) -> dict[str, object]:
    return {
        "authentication_ref": observation.authentication_ref,
        "bypass_row_level_security": observation.bypass_row_level_security,
        "can_login": observation.can_login,
        "create_database": observation.create_database,
        "create_role": observation.create_role,
        "evidence_cutoff": _timestamp(observation.evidence_cutoff),
        "evidence_ref": observation.evidence_ref,
        "freshness_ceiling_seconds": observation.freshness_ceiling_seconds,
        "inherit": observation.inherit,
        "observation_id": observation.observation_id,
        "observed_at": _timestamp(observation.observed_at),
        "recorded_at": _timestamp(observation.recorded_at),
        "replication": observation.replication,
        "role_name": observation.role_name,
        "scope_ref": observation.scope_ref,
        "service_ref": observation.service_ref,
        "source_identity": observation.source_identity,
        "source_revision": observation.source_revision,
        "superuser": observation.superuser,
    }


def _evidence_body(evidence: PostgresRoleEvidence | None) -> dict[str, object] | None:
    if evidence is None:
        return None
    return {
        "bypass_row_level_security": evidence.bypass_row_level_security,
        "can_login": evidence.can_login,
        "create_database": evidence.create_database,
        "create_role": evidence.create_role,
        "evidence_cutoff": _timestamp(evidence.evidence_cutoff),
        "evidence_refs": evidence.evidence_refs,
        "freshness_ceiling_seconds": evidence.freshness_ceiling_seconds,
        "inherit": evidence.inherit,
        "observed_at": _timestamp(evidence.observed_at),
        "principal_handle": evidence.principal_handle,
        "recorded_at": _timestamp(evidence.recorded_at),
        "replication": evidence.replication,
        "service_ref": evidence.service_ref,
        "source_identity": evidence.source_identity,
        "source_revision": evidence.source_revision,
        "superuser": evidence.superuser,
    }


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_digest(value: str) -> bool:
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "PostgresRoleEvidence",
    "PostgresRoleObservation",
    "PostgresRoleProjection",
    "PostgresRoleProjectionReason",
    "project_postgres_role_evidence",
]
