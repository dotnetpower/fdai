"""Environment-independent operational-case learning projection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import CaseKind, CaseSourceRecord

_SCHEMA_VERSION = "1.0.0"
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_ITEMS = 32
_MAX_RECEIPTS = 16


class OperationalReceiptType(StrEnum):
    AUDIT = "audit"
    ACTION = "action"
    RESPONSE_OUTCOME = "response_outcome"
    EVALUATION = "evaluation"


class OperationalOutcomeClass(StrEnum):
    SUCCESS = "success"
    NO_OP = "no_op"
    REFUSAL = "refusal"
    ROLLBACK = "rollback"
    RECURRENCE = "recurrence"
    FAILURE = "failure"


_RECEIPT_FIELDS: dict[OperationalReceiptType, frozenset[str]] = {
    OperationalReceiptType.AUDIT: frozenset({"event_type", "decision", "mode"}),
    OperationalReceiptType.ACTION: frozenset(
        {
            "action_type",
            "execution_outcome",
            "dry_run_digest",
            "terminal_receipt_digest",
            "rollback_receipt_digest",
            "affected_resource_count",
        }
    ),
    OperationalReceiptType.RESPONSE_OUTCOME: frozenset(
        {
            "label",
            "verification_status",
            "execution_outcome",
            "rollback_succeeded",
            "recurrence",
        }
    ),
    OperationalReceiptType.EVALUATION: frozenset(
        {"validation_status", "evidence_digest", "operationalized", "azure_validated"}
    ),
}
_REQUIRED_RECEIPT_FIELDS: dict[OperationalReceiptType, frozenset[str]] = {
    OperationalReceiptType.AUDIT: frozenset({"event_type", "decision", "mode"}),
    OperationalReceiptType.ACTION: frozenset(
        {"action_type", "execution_outcome", "dry_run_digest", "terminal_receipt_digest"}
    ),
    OperationalReceiptType.RESPONSE_OUTCOME: frozenset(
        {"label", "verification_status", "execution_outcome"}
    ),
    OperationalReceiptType.EVALUATION: frozenset({"validation_status", "evidence_digest"}),
}
_DIGEST_FIELDS = frozenset(
    {"dry_run_digest", "terminal_receipt_digest", "rollback_receipt_digest", "evidence_digest"}
)
_BOOLEAN_FIELDS = frozenset(
    {"rollback_succeeded", "recurrence", "operationalized", "azure_validated"}
)
_ENUM_FACT_VALUES: dict[str, frozenset[str]] = {
    "decision": frozenset({"auto", "hil", "deny", "abstain"}),
    "mode": frozenset({"shadow", "enforce"}),
    "execution_outcome": frozenset(item.value for item in OperationalOutcomeClass),
    "label": frozenset({"verified", "mismatch", "unscorable"}),
    "verification_status": frozenset({"verified", "mismatch", "hold"}),
    "validation_status": frozenset({"accepted", "rejected", "held"}),
}


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


OperationalFactValue = str | bool | int


@dataclass(frozen=True, slots=True)
class OperationalReceiptFact:
    receipt_type: OperationalReceiptType
    receipt_digest: str
    occurred_at: datetime
    facts: tuple[tuple[str, OperationalFactValue], ...]

    def __post_init__(self) -> None:
        if not _is_sha256(self.receipt_digest):
            raise ValueError("operational receipt digest MUST be lowercase SHA-256")
        if self.occurred_at.tzinfo is None:
            raise ValueError("operational receipt timestamp MUST be timezone-aware")
        facts = tuple(
            sorted((key, _normalize_receipt_fact(key, value)) for key, value in self.facts)
        )
        keys = {key for key, _ in facts}
        allowed = _RECEIPT_FIELDS[self.receipt_type]
        required = _REQUIRED_RECEIPT_FIELDS[self.receipt_type]
        if len(keys) != len(facts) or not required.issubset(keys) or not keys.issubset(allowed):
            raise ValueError("operational receipt facts do not match their standard schema")
        object.__setattr__(self, "facts", facts)


@dataclass(frozen=True, slots=True)
class OperationalCaseInput:
    case_identity_digest: str
    kind: CaseKind
    correlation_digest: str
    purpose: str
    access_scope_digest: str
    redaction_policy_version: str
    event_time_cutoff: datetime
    failure_fingerprint: FailureFingerprint
    action_type: str
    outcome_class: OperationalOutcomeClass
    evidence_refs: tuple[str, ...]
    receipts: tuple[OperationalReceiptFact, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("case identity", self.case_identity_digest),
            ("correlation", self.correlation_digest),
            ("access scope", self.access_scope_digest),
        ):
            if not _is_sha256(value):
                raise ValueError(f"operational case {name} MUST be lowercase SHA-256")
        if self.kind not in {CaseKind.ACTION, CaseKind.INCIDENT}:
            raise ValueError("operational case kind MUST be action or incident")
        object.__setattr__(self, "purpose", _identifier("purpose", self.purpose))
        object.__setattr__(
            self,
            "redaction_policy_version",
            _identifier("redaction_policy_version", self.redaction_policy_version),
        )
        object.__setattr__(self, "action_type", _identifier("action_type", self.action_type))
        if self.event_time_cutoff.tzinfo is None:
            raise ValueError("operational case cutoff MUST be timezone-aware")
        evidence_refs = tuple(sorted(set(self.evidence_refs)))
        if not evidence_refs or any(not _is_sha256(value) for value in evidence_refs):
            raise ValueError("operational case evidence refs MUST be SHA-256 digests")
        if len(evidence_refs) > _MAX_ITEMS:
            raise ValueError("operational case evidence refs exceed their item limit")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        receipts = tuple(
            sorted(self.receipts, key=lambda item: (item.occurred_at, item.receipt_type.value))
        )
        receipt_types = {receipt.receipt_type for receipt in receipts}
        required_types = {
            OperationalReceiptType.AUDIT,
            OperationalReceiptType.ACTION,
            OperationalReceiptType.RESPONSE_OUTCOME,
        }
        if not required_types.issubset(receipt_types):
            raise ValueError(
                "operational case requires audit, action, and response outcome receipts"
            )
        if not receipts or len(receipts) > _MAX_RECEIPTS:
            raise ValueError("operational case receipt count is invalid")
        if len({receipt.receipt_digest for receipt in receipts}) != len(receipts):
            raise ValueError("operational case receipt identities MUST be unique")
        for receipt in receipts:
            facts = dict(receipt.facts)
            if (
                receipt.receipt_type is OperationalReceiptType.ACTION
                and facts["action_type"] != self.action_type
            ):
                raise ValueError("operational action receipt MUST match the case action type")
            if (
                receipt.receipt_type
                in {
                    OperationalReceiptType.ACTION,
                    OperationalReceiptType.RESPONSE_OUTCOME,
                }
                and facts["execution_outcome"] != self.outcome_class.value
            ):
                raise ValueError("operational receipt outcome MUST match the case outcome")
        object.__setattr__(self, "receipts", receipts)


@dataclass(frozen=True, slots=True)
class CompiledOperationalCase:
    case_input: OperationalCaseInput
    sources: tuple[CaseSourceRecord, ...]

    def projection(
        self,
        *,
        case_id: str,
        case_revision: int,
        manifest_digest: str,
    ) -> OperationalCaseProjection:
        return OperationalCaseProjection(
            case_id=case_id,
            case_revision=case_revision,
            manifest_digest=manifest_digest,
            failure_fingerprint=self.case_input.failure_fingerprint,
            action_type=self.case_input.action_type,
            outcome_class=self.case_input.outcome_class,
            evidence_refs=self.case_input.evidence_refs,
        )


def compile_operational_case(case_input: OperationalCaseInput) -> CompiledOperationalCase:
    projection_payload = {
        "action_type": case_input.action_type,
        "evidence_refs": case_input.evidence_refs,
        "failure_fingerprint": case_input.failure_fingerprint.digest,
        "outcome_class": case_input.outcome_class.value,
        "resource_type": case_input.failure_fingerprint.resource_type,
    }
    projection_bytes = json.dumps(
        projection_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    sources: list[CaseSourceRecord] = [
        CaseSourceRecord(
            record_type="operational-case-projection",
            record_id=case_input.case_identity_digest,
            record_digest=hashlib.sha256(projection_bytes).hexdigest(),
            occurred_at=case_input.event_time_cutoff,
            payload=projection_payload,
        )
    ]
    for receipt in case_input.receipts:
        payload = {key: value for key, value in receipt.facts}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sources.append(
            CaseSourceRecord(
                record_type=f"operational-{receipt.receipt_type.value}-receipt",
                record_id=receipt.receipt_digest,
                record_digest=hashlib.sha256(canonical).hexdigest(),
                occurred_at=receipt.occurred_at,
                payload=payload,
            )
        )
    return CompiledOperationalCase(case_input=case_input, sources=tuple(sources))


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


def _normalize_receipt_fact(key: str, value: OperationalFactValue) -> OperationalFactValue:
    if key in _DIGEST_FIELDS:
        if not isinstance(value, str) or not _is_sha256(value):
            raise ValueError(f"operational receipt {key} MUST be lowercase SHA-256")
        return value
    if key in _BOOLEAN_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"operational receipt {key} MUST be boolean")
        return value
    if key == "affected_resource_count":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
            raise ValueError("operational receipt affected_resource_count MUST be in [0, 10000]")
        return value
    if not isinstance(value, str):
        raise ValueError(f"operational receipt {key} MUST be a canonical identifier")
    normalized = _identifier(key, value)
    allowed = _ENUM_FACT_VALUES.get(key)
    if allowed is not None and normalized not in allowed:
        raise ValueError(f"operational receipt {key} is unsupported")
    return normalized


__all__ = [
    "CompiledOperationalCase",
    "FailureFingerprint",
    "OperationalCaseInput",
    "OperationalCaseProjection",
    "OperationalOutcomeClass",
    "OperationalReceiptFact",
    "OperationalReceiptType",
    "compile_operational_case",
]
