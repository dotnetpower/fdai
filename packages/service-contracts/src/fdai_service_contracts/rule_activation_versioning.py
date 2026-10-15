"""Binary-rollback codecs for versioned Rule activation records and events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

RULE_ACTIVATION_WRITE_SCHEMA_VERSION = "1.0.0"
RULE_ACTIVATION_READ_SCHEMA_VERSIONS = frozenset({"1.0.0", "2.0.0"})


class RuleActivationRecordKind(StrEnum):
    """Durable objects and events covered by the Rule activation rollback floor."""

    PROPOSAL = "rule_activation.proposal"
    CHANGE = "rule_activation.change"
    APPROVAL = "rule_activation.approval"
    COMMAND = "rule_activation.command"
    RESULT = "rule_activation.result"
    REQUEST = "rule_activation.request"
    POINTER = "rule_activation.current"
    GENERATION = "rule_activation.generation"
    IDEMPOTENCY = "rule_activation.idempotency"
    MANIFEST = "rule_activation.manifest"
    PREPARE = "rule_activation.prepare"
    ACKNOWLEDGEMENT = "rule_activation.acknowledgement"


@dataclass(frozen=True, slots=True)
class DecodedRuleActivationRecord:
    """One validated envelope with its source schema retained for audit."""

    schema_version: str
    kind: RuleActivationRecordKind
    body: Mapping[str, object]


def encode_rule_activation_record(
    kind: RuleActivationRecordKind,
    body: Mapping[str, object],
) -> dict[str, object]:
    """Write the phase-1 version while later phases remain dormant."""

    validated = _body(body)
    if "schema_version" in validated or "kind" in validated:
        raise ValueError("Rule activation record body contains reserved envelope fields")
    return {
        "schema_version": RULE_ACTIVATION_WRITE_SCHEMA_VERSION,
        "kind": kind.value,
        **validated,
    }


def decode_rule_activation_record(
    value: Mapping[str, object],
    *,
    expected_kind: RuleActivationRecordKind,
) -> DecodedRuleActivationRecord:
    """Read an exact version 1 or 2 envelope and reject every other shape."""

    raw = _body(value)
    schema_version = raw.pop("schema_version", None)
    kind = raw.pop("kind", None)
    if schema_version not in RULE_ACTIVATION_READ_SCHEMA_VERSIONS:
        raise ValueError("Rule activation record schema version is unsupported")
    if kind != expected_kind.value:
        raise ValueError("Rule activation record kind is invalid")
    return DecodedRuleActivationRecord(
        schema_version=str(schema_version),
        kind=expected_kind,
        body=MappingProxyType(raw),
    )


def canonicalize_rule_activation_payload(value: Mapping[str, object]) -> dict[str, object]:
    """Convert a readable v1/v2 contract payload to the phase-1 model version."""

    raw = _body(value)
    schema_version = raw.get("schema_version")
    if schema_version not in RULE_ACTIVATION_READ_SCHEMA_VERSIONS:
        raise ValueError("Rule activation payload schema version is unsupported")
    raw["schema_version"] = RULE_ACTIVATION_WRITE_SCHEMA_VERSION
    return raw


def _body(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("Rule activation record MUST be an object with string keys")
    return dict(value)


__all__ = [
    "DecodedRuleActivationRecord",
    "RULE_ACTIVATION_READ_SCHEMA_VERSIONS",
    "RULE_ACTIVATION_WRITE_SCHEMA_VERSION",
    "RuleActivationRecordKind",
    "canonicalize_rule_activation_payload",
    "decode_rule_activation_record",
    "encode_rule_activation_record",
]
