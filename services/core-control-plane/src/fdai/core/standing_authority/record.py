"""Typed A3-E standing-authorization records.

FDAI-CONST-008 defines A3-E as approval given in advance, never approval inferred from
silence. A record is a reviewed, revocable, time-bounded delegation that names exactly what
may run, where, for how long, and under whose authority.

This module parses and canonicalizes such a record and rejects anything malformed instead
of defaulting. It grants no authority by itself: parsing a record proves only that the
document is well formed. :mod:`fdai.core.standing_authority.evaluator` decides eligibility,
and nothing in the shipped runtime consumes either module yet.

`mode` accepts only `shadow`. Enforce requires a governed shadow cohort with zero envelope
escapes and an independent promotion review, neither of which exists.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import resources
from typing import Any, Self

SCHEMA_PACKAGE = "fdai.shared.contracts"
SCHEMA_RESOURCE = "authority/standing-authorization.json"


class StandingAuthorizationError(ValueError):
    """Raised when a standing-authorization document cannot be admitted."""


class AuthorizationStatus(StrEnum):
    """Lifecycle state of one standing authorization."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AuthorizationMode(StrEnum):
    """Only shadow ships; enforce has no promotion path."""

    SHADOW = "shadow"


class ApproverRole(StrEnum):
    """Authority class an approving human held at approval time."""

    SERVICE_OWNER = "service_owner"
    OWNER = "owner"
    APPROVER = "approver"


class ScopeLevel(StrEnum):
    """Resource-group-equivalent or narrower; wider scope is never eligible."""

    RESOURCE = "resource"
    RESOURCE_GROUP = "resource_group"


@dataclass(frozen=True, slots=True)
class Approval:
    """One human approval with its authority class and instant."""

    principal: str
    role: ApproverRole
    approved_at: datetime

    @property
    def normalized_principal(self) -> str:
        """Return the case-folded principal used for distinctness checks."""

        return self.principal.strip().casefold()


@dataclass(frozen=True, slots=True)
class AuthorizationScope:
    """Where the delegation applies."""

    level: ScopeLevel
    value: str


@dataclass(frozen=True, slots=True)
class AuthorizationPins:
    """The exact revisions the delegation was reviewed against."""

    policy_digest: str
    target_revision: str
    action_type_versions: tuple[str, ...]
    evidence_revisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorizationEnvelope:
    """The bounded impact the delegation permits."""

    action_types: tuple[str, ...]
    max_blast_radius: int
    max_duration_seconds: int
    reversible: bool
    rollback_contract: str
    stop_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Responders:
    """Current primary and backup responders and their confirmation instant."""

    primary: str
    backup: str
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizationEvidence:
    """What was reviewed before the delegation was granted."""

    history_reviewed: bool
    precedent_ref: str | None = None
    scenario_evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class StandingAuthorization:
    """One parsed, well-formed A3-E delegation with no authority of its own."""

    schema_version: str
    id: str
    authorization_revision: str
    status: AuthorizationStatus
    mode: AuthorizationMode
    requested_by: str
    approvals: tuple[Approval, ...]
    quorum_required: int
    valid_from: datetime
    valid_until: datetime
    service_ref: str
    scope: AuthorizationScope
    pins: AuthorizationPins
    envelope: AuthorizationEnvelope
    incident_classes: tuple[str, ...]
    responders: Responders
    evidence: AuthorizationEvidence

    def __post_init__(self) -> None:
        if self.valid_from >= self.valid_until:
            raise StandingAuthorizationError("valid_from MUST precede valid_until")
        if self.quorum_required < 2:
            raise StandingAuthorizationError("quorum_required MUST be at least 2")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Parse one document, rejecting anything the schema does not allow."""

        _validate_against_schema(value)
        return cls(
            schema_version=_text(value, "schema_version"),
            id=_text(value, "id"),
            authorization_revision=_text(value, "authorization_revision"),
            status=AuthorizationStatus(_text(value, "status")),
            mode=AuthorizationMode(_text(value, "mode")),
            requested_by=_text(value, "requested_by"),
            approvals=tuple(
                Approval(
                    principal=_text(item, "principal"),
                    role=ApproverRole(_text(item, "role")),
                    approved_at=_instant(item, "approved_at"),
                )
                for item in _sequence(value, "approvals")
            ),
            quorum_required=_integer(value, "quorum_required"),
            valid_from=_instant(value, "valid_from"),
            valid_until=_instant(value, "valid_until"),
            service_ref=_text(value, "service_ref"),
            scope=AuthorizationScope(
                level=ScopeLevel(_text(_mapping(value, "scope"), "level")),
                value=_text(_mapping(value, "scope"), "value"),
            ),
            pins=AuthorizationPins(
                policy_digest=_text(_mapping(value, "pins"), "policy_digest"),
                target_revision=_text(_mapping(value, "pins"), "target_revision"),
                action_type_versions=_text_tuple(_mapping(value, "pins"), "action_type_versions"),
                evidence_revisions=_text_tuple(_mapping(value, "pins"), "evidence_revisions"),
            ),
            envelope=AuthorizationEnvelope(
                action_types=_text_tuple(_mapping(value, "envelope"), "action_types"),
                max_blast_radius=_integer(_mapping(value, "envelope"), "max_blast_radius"),
                max_duration_seconds=_integer(_mapping(value, "envelope"), "max_duration_seconds"),
                reversible=_boolean(_mapping(value, "envelope"), "reversible"),
                rollback_contract=_text(_mapping(value, "envelope"), "rollback_contract"),
                stop_conditions=_text_tuple(_mapping(value, "envelope"), "stop_conditions"),
            ),
            incident_classes=_text_tuple(value, "incident_classes"),
            responders=Responders(
                primary=_text(_mapping(value, "responders"), "primary"),
                backup=_text(_mapping(value, "responders"), "backup"),
                confirmed_at=_instant(_mapping(value, "responders"), "confirmed_at"),
            ),
            evidence=AuthorizationEvidence(
                history_reviewed=_boolean(_mapping(value, "evidence"), "history_reviewed"),
                precedent_ref=_optional_text(_mapping(value, "evidence"), "precedent_ref"),
                scenario_evidence_ref=_optional_text(
                    _mapping(value, "evidence"), "scenario_evidence_ref"
                ),
            ),
        )


def load_schema() -> Mapping[str, Any]:
    """Return the shipped standing-authorization JSON Schema."""

    raw = resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8")
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):  # pragma: no cover - the shipped file is an object
        raise StandingAuthorizationError("the standing-authorization schema is not a JSON object")
    return loaded


def _validate_against_schema(value: Mapping[str, Any]) -> None:
    from jsonschema import Draft202012Validator

    errors = sorted(
        Draft202012Validator(dict(load_schema())).iter_errors(dict(value)),
        key=lambda error: list(error.path),
    )
    if errors:
        raise StandingAuthorizationError(
            "standing authorization is invalid: " + "; ".join(error.message for error in errors[:3])
        )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    child = value.get(key)
    if not isinstance(child, Mapping):
        raise StandingAuthorizationError(f"{key!r} MUST be an object")
    return child


def _sequence(value: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    child = value.get(key)
    if not isinstance(child, Sequence) or isinstance(child, (str, bytes)):
        raise StandingAuthorizationError(f"{key!r} MUST be an array")
    for item in child:
        if not isinstance(item, Mapping):
            raise StandingAuthorizationError(f"{key!r} entries MUST be objects")
    return list(child)


def _text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise StandingAuthorizationError(f"{key!r} MUST be a non-empty string")
    return raw.strip()


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    return _text(value, key)


def _text_tuple(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise StandingAuthorizationError(f"{key!r} MUST be an array of strings")
    entries: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise StandingAuthorizationError(f"{key!r} entries MUST be non-empty strings")
        entries.append(item.strip())
    return tuple(entries)


def _integer(value: Mapping[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise StandingAuthorizationError(f"{key!r} MUST be an integer")
    return raw


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    raw = value.get(key)
    if not isinstance(raw, bool):
        raise StandingAuthorizationError(f"{key!r} MUST be a boolean")
    return raw


def _instant(value: Mapping[str, Any], key: str) -> datetime:
    raw = _text(value, key)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StandingAuthorizationError(f"{key!r} MUST be an RFC 3339 instant") from exc
    if parsed.tzinfo is None:
        raise StandingAuthorizationError(f"{key!r} MUST carry an explicit timezone")
    return parsed.astimezone(UTC)


__all__ = [
    "SCHEMA_PACKAGE",
    "SCHEMA_RESOURCE",
    "Approval",
    "ApproverRole",
    "AuthorizationEnvelope",
    "AuthorizationEvidence",
    "AuthorizationMode",
    "AuthorizationPins",
    "AuthorizationScope",
    "AuthorizationStatus",
    "Responders",
    "ScopeLevel",
    "StandingAuthorization",
    "StandingAuthorizationError",
    "load_schema",
]
