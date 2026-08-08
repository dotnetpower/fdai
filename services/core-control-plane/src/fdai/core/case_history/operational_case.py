"""Environment-independent operational-case learning projection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import CaseKind, CaseSourceRecord

_SCHEMA_VERSION = "1.0.0"
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_IDENTIFIER_CHARS = 128
_MAX_ITEMS = 32
_MAX_RECEIPTS = 16
_MAX_WIRE_BYTES = 64 * 1024


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

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "resource_type": self.resource_type,
            "failure_mechanism": self.failure_mechanism,
            "symptom_codes": list(self.symptom_codes),
            "topology_roles": list(self.topology_roles),
            "ownership_shape": list(self.ownership_shape),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> FailureFingerprint:
        _require_standard_schema(
            value,
            {
                "schema_version",
                "resource_type",
                "failure_mechanism",
                "symptom_codes",
                "topology_roles",
                "ownership_shape",
            },
            "failure fingerprint",
        )
        return cls(
            schema_version=_required_string(value, "schema_version"),
            resource_type=_required_string(value, "resource_type"),
            failure_mechanism=_required_string(value, "failure_mechanism"),
            symptom_codes=_string_array(value, "symptom_codes"),
            topology_roles=_string_array(value, "topology_roles"),
            ownership_shape=_string_array(value, "ownership_shape"),
        )


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

    def to_mapping(self) -> dict[str, object]:
        return {
            "receipt_type": self.receipt_type.value,
            "receipt_digest": self.receipt_digest,
            "occurred_at": self.occurred_at.isoformat(),
            "facts": dict(self.facts),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationalReceiptFact:
        _require_standard_schema(
            value,
            {"receipt_type", "receipt_digest", "occurred_at", "facts"},
            "operational receipt",
        )
        facts = value.get("facts")
        if not isinstance(facts, Mapping):
            raise ValueError("operational receipt facts MUST be an object")
        try:
            receipt_type = OperationalReceiptType(_required_string(value, "receipt_type"))
        except ValueError as exc:
            raise ValueError("operational receipt type is unsupported") from exc
        return cls(
            receipt_type=receipt_type,
            receipt_digest=_required_string(value, "receipt_digest"),
            occurred_at=_required_datetime(value, "occurred_at"),
            facts=tuple((str(key), item) for key, item in facts.items()),
        )


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
        authoritative = (
            OperationalReceiptType.AUDIT,
            OperationalReceiptType.ACTION,
            OperationalReceiptType.RESPONSE_OUTCOME,
        )
        if any(
            sum(receipt.receipt_type is receipt_type for receipt in receipts) != 1
            for receipt_type in authoritative
        ):
            raise ValueError("operational case authoritative receipt types MUST be unique")
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
            if receipt.receipt_type is OperationalReceiptType.RESPONSE_OUTCOME:
                for flag, expected_outcome in (
                    ("rollback_succeeded", OperationalOutcomeClass.ROLLBACK),
                    ("recurrence", OperationalOutcomeClass.RECURRENCE),
                ):
                    declared = facts.get(flag) is True
                    expected = self.outcome_class is expected_outcome
                    if declared != expected:
                        raise ValueError(
                            f"operational response receipt {flag} MUST match the case outcome"
                        )
        object.__setattr__(self, "receipts", receipts)

    def to_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "case_identity_digest": self.case_identity_digest,
            "kind": self.kind.value,
            "correlation_digest": self.correlation_digest,
            "purpose": self.purpose,
            "access_scope_digest": self.access_scope_digest,
            "redaction_policy_version": self.redaction_policy_version,
            "event_time_cutoff": self.event_time_cutoff.isoformat(),
            "failure_fingerprint": self.failure_fingerprint.to_mapping(),
            "action_type": self.action_type,
            "outcome_class": self.outcome_class.value,
            "evidence_refs": list(self.evidence_refs),
            "receipts": [receipt.to_mapping() for receipt in self.receipts],
        }
        _validate_wire_size(mapping)
        return mapping

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> OperationalCaseInput:
        _validate_wire_size(value)
        _require_standard_schema(
            value,
            {
                "case_identity_digest",
                "kind",
                "correlation_digest",
                "purpose",
                "access_scope_digest",
                "redaction_policy_version",
                "event_time_cutoff",
                "failure_fingerprint",
                "action_type",
                "outcome_class",
                "evidence_refs",
                "receipts",
            },
            "operational case",
        )
        fingerprint = value.get("failure_fingerprint")
        if not isinstance(fingerprint, Mapping):
            raise ValueError("operational case failure_fingerprint MUST be an object")
        receipts = value.get("receipts")
        if not isinstance(receipts, Sequence) or isinstance(receipts, str | bytes):
            raise ValueError("operational case receipts MUST be an array")
        if any(not isinstance(receipt, Mapping) for receipt in receipts):
            raise ValueError("operational case receipts MUST contain objects")
        try:
            kind = CaseKind(_required_string(value, "kind"))
            outcome_class = OperationalOutcomeClass(_required_string(value, "outcome_class"))
        except ValueError as exc:
            raise ValueError("operational case enum value is unsupported") from exc
        return cls(
            case_identity_digest=_required_string(value, "case_identity_digest"),
            kind=kind,
            correlation_digest=_required_string(value, "correlation_digest"),
            purpose=_required_string(value, "purpose"),
            access_scope_digest=_required_string(value, "access_scope_digest"),
            redaction_policy_version=_required_string(value, "redaction_policy_version"),
            event_time_cutoff=_required_datetime(value, "event_time_cutoff"),
            failure_fingerprint=FailureFingerprint.from_mapping(fingerprint),
            action_type=_required_string(value, "action_type"),
            outcome_class=outcome_class,
            evidence_refs=_string_array(value, "evidence_refs"),
            receipts=tuple(OperationalReceiptFact.from_mapping(receipt) for receipt in receipts),
        )


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
    if len(normalized) > _MAX_IDENTIFIER_CHARS or not _IDENTIFIER.fullmatch(normalized):
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


def _require_standard_schema(
    value: Mapping[str, object],
    expected: set[str],
    name: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} mapping does not match its standard schema")


def _validate_wire_size(value: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("operational case wire payload MUST be canonical JSON") from exc
    if len(encoded) > _MAX_WIRE_BYTES:
        raise ValueError("operational case wire payload exceeds its byte limit")


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"operational case field {key!r} MUST be a non-empty string")
    return item


def _required_datetime(value: Mapping[str, object], key: str) -> datetime:
    raw = _required_string(value, key)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"operational case field {key!r} MUST be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"operational case field {key!r} MUST be timezone-aware")
    return parsed


def _string_array(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError(f"operational case field {key!r} MUST be an array")
    if any(not isinstance(item, str) for item in raw):
        raise ValueError(f"operational case field {key!r} MUST contain strings")
    return tuple(raw)


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
