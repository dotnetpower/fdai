"""Dual-read, single-publish parity contracts for W6 cutover."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIELDS = (
    "decision",
    "reasons",
    "topic",
    "payload",
    "audit_fields",
    "ontology_lineage",
)


class CostParityError(ValueError):
    """Parity or single-writer evidence is invalid."""


class CostParityOwner(StrEnum):
    LEGACY = "legacy"
    PACKAGE = "package"


@dataclass(frozen=True, slots=True)
class CostParityRecord:
    """Comparable typed decision/event/audit projection for one frozen case."""

    case_id: str
    implementation: CostParityOwner
    decision: str
    reasons: tuple[str, ...]
    topic: str
    payload: Mapping[str, Any]
    audit_fields: Mapping[str, Any]
    ontology_lineage: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.case_id or not self.decision or not self.topic:
            raise CostParityError("parity record identity fields MUST be non-empty")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "audit_fields",
            MappingProxyType(dict(self.audit_fields)),
        )
        lineage = dict(self.ontology_lineage)
        if set(lineage) != {
            "ontology_release_digest",
            "semantic_profile_digest",
        } or any(_SHA256.fullmatch(value) is None for value in lineage.values()):
            raise CostParityError("parity ontology lineage MUST pin exact SHA-256 identities")
        object.__setattr__(self, "ontology_lineage", MappingProxyType(lineage))

    def comparable(self) -> Mapping[str, Any]:
        return {
            "decision": self.decision,
            "reasons": list(self.reasons),
            "topic": self.topic,
            "payload": dict(self.payload),
            "audit_fields": dict(self.audit_fields),
            "ontology_lineage": dict(self.ontology_lineage),
        }


@dataclass(frozen=True, slots=True)
class ApprovedParityDifference:
    """One exact, reviewed, versioned field difference."""

    mechanism_version: str
    approval_id: str
    case_id: str
    field: str
    legacy_value_digest: str
    package_value_digest: str

    def __post_init__(self) -> None:
        if self.mechanism_version != "1.0.0":
            raise CostParityError("parity difference mechanism version is unsupported")
        if not self.approval_id or self.field not in _FIELDS:
            raise CostParityError("parity difference approval identity is invalid")
        for digest in (self.legacy_value_digest, self.package_value_digest):
            if _SHA256.fullmatch(digest) is None:
                raise CostParityError("parity difference values MUST use SHA-256 digests")


@dataclass(frozen=True, slots=True)
class CostParityReport:
    case_count: int
    approved_difference_count: int
    selected_owner: CostParityOwner
    publication_records: tuple[CostParityRecord, ...]


def value_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CostGovernanceParityHarness:
    """Compare both readers and expose records for exactly one selected publisher."""

    def compare(
        self,
        *,
        legacy: tuple[CostParityRecord, ...],
        package: tuple[CostParityRecord, ...],
        selected_owner: CostParityOwner,
        publisher_claims: tuple[CostParityOwner, ...],
        approved_differences: tuple[ApprovedParityDifference, ...] = (),
    ) -> CostParityReport:
        legacy_by_case = _records_by_case(legacy, CostParityOwner.LEGACY)
        package_by_case = _records_by_case(package, CostParityOwner.PACKAGE)
        if set(legacy_by_case) != set(package_by_case):
            raise CostParityError("legacy and package parity case sets differ")
        if len(publisher_claims) > 1:
            raise CostParityError("dual-writer publication is prohibited")
        claims = set(publisher_claims)
        if claims and claims != {selected_owner}:
            raise CostParityError("only the selected Cost Governance owner may publish")

        approvals = {(item.case_id, item.field): item for item in approved_differences}
        if len(approvals) != len(approved_differences):
            raise CostParityError("parity difference approvals MUST be unique")
        used: set[tuple[str, str]] = set()
        for case_id in sorted(legacy_by_case):
            legacy_values = legacy_by_case[case_id].comparable()
            package_values = package_by_case[case_id].comparable()
            for field in _FIELDS:
                if legacy_values[field] == package_values[field]:
                    continue
                approval = approvals.get((case_id, field))
                if approval is None:
                    raise CostParityError(f"unapproved parity difference: {case_id}:{field}")
                if approval.legacy_value_digest != value_digest(
                    legacy_values[field]
                ) or approval.package_value_digest != value_digest(package_values[field]):
                    raise CostParityError(f"parity difference digest mismatch: {case_id}:{field}")
                used.add((case_id, field))
        unused = set(approvals) - used
        if unused:
            raise CostParityError(f"unused parity difference approvals: {sorted(unused)}")
        selected = package if selected_owner is CostParityOwner.PACKAGE else legacy
        publications = selected if claims else ()
        return CostParityReport(
            case_count=len(legacy_by_case),
            approved_difference_count=len(used),
            selected_owner=selected_owner,
            publication_records=publications,
        )


def _records_by_case(
    records: tuple[CostParityRecord, ...],
    expected_owner: CostParityOwner,
) -> dict[str, CostParityRecord]:
    result: dict[str, CostParityRecord] = {}
    for record in records:
        if record.implementation is not expected_owner:
            raise CostParityError("parity record implementation owner is invalid")
        if record.case_id in result:
            raise CostParityError(f"duplicate parity case id: {record.case_id}")
        result[record.case_id] = record
    if not result:
        raise CostParityError("parity corpus MUST be non-empty")
    return result


__all__ = [
    "ApprovedParityDifference",
    "CostGovernanceParityHarness",
    "CostParityError",
    "CostParityOwner",
    "CostParityRecord",
    "CostParityReport",
    "value_digest",
]
