"""Environment-independent operational-case learning projection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

_SCHEMA_VERSION = "1.0.0"
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_ITEMS = 32


class OperationalOutcomeClass(StrEnum):
    SUCCESS = "success"
    NO_OP = "no_op"
    REFUSAL = "refusal"
    ROLLBACK = "rollback"
    RECURRENCE = "recurrence"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class FailureFingerprint:
    resource_type: str
    failure_mechanism: str
    symptom_codes: tuple[str, ...]
    topology_roles: tuple[str, ...]
    ownership_shape: tuple[str, ...]
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("failure fingerprint schema version MUST be 1.0.0")
        object.__setattr__(self, "resource_type", _identifier("resource_type", self.resource_type))
        object.__setattr__(
            self,
            "failure_mechanism",
            _identifier("failure_mechanism", self.failure_mechanism),
        )
        object.__setattr__(self, "symptom_codes", _identifiers("symptom_codes", self.symptom_codes))
        object.__setattr__(
            self,
            "topology_roles",
            _identifiers("topology_roles", self.topology_roles),
        )
        object.__setattr__(
            self,
            "ownership_shape",
            _identifiers("ownership_shape", self.ownership_shape),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "failure_mechanism": self.failure_mechanism,
                "ownership_shape": self.ownership_shape,
                "resource_type": self.resource_type,
                "schema_version": self.schema_version,
                "symptom_codes": self.symptom_codes,
                "topology_roles": self.topology_roles,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


@dataclass(frozen=True, slots=True)
class OperationalCaseProjection:
    case_id: str
    case_revision: int
    manifest_digest: str
    failure_fingerprint: FailureFingerprint
    action_type: str
    outcome_class: OperationalOutcomeClass
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("operational case id MUST be non-empty")
        if self.case_revision < 1:
            raise ValueError("operational case revision MUST be positive")
        if not _is_sha256(self.manifest_digest):
            raise ValueError("operational case manifest digest MUST be lowercase SHA-256")
        object.__setattr__(self, "action_type", _identifier("action_type", self.action_type))
        evidence_refs = tuple(sorted(set(self.evidence_refs)))
        if not evidence_refs or any(not value for value in evidence_refs):
            raise ValueError("operational case evidence refs MUST be non-empty")
        if len(evidence_refs) > _MAX_ITEMS:
            raise ValueError("operational case evidence refs exceed their item limit")
        object.__setattr__(self, "evidence_refs", evidence_refs)


def _identifier(name: str, value: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"failure fingerprint {name} MUST be a canonical identifier")
    return normalized


def _identifiers(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({_identifier(name, value) for value in values}))
    if not normalized:
        raise ValueError(f"failure fingerprint {name} MUST be non-empty")
    if len(normalized) > _MAX_ITEMS:
        raise ValueError(f"failure fingerprint {name} exceeds its item limit")
    return normalized


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "FailureFingerprint",
    "OperationalCaseProjection",
    "OperationalOutcomeClass",
]
