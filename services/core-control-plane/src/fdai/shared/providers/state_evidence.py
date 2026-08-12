"""Immutable provider-neutral metadata for decision-relevant state and links."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

STATE_FACT_METADATA_PROPERTY = "state_fact_metadata"
LINK_OBSERVATION_METADATA_PROPERTY = "link_observation_metadata"
TRUSTED_LINK_VERIFICATION_METHODS = frozenset(
    {"deterministic-cross-check", "independent-source", "provider-readback"}
)


class StateFactLane(StrEnum):
    """Authority-separated lane for one runtime state fact."""

    OBSERVED = "observed"
    DERIVED = "derived"
    DESIRED = "desired"
    EXECUTION = "execution"


class StateFactAuthority(StrEnum):
    """Authority class allowed to originate one state-fact lane."""

    PROVIDER = "provider"
    TELEMETRY = "telemetry"
    DETERMINISTIC_FUNCTION = "deterministic_function"
    APPROVED_POLICY = "approved_policy"
    EXECUTION_LEDGER = "execution_ledger"


_LANE_AUTHORITIES: dict[StateFactLane, frozenset[StateFactAuthority]] = {
    StateFactLane.OBSERVED: frozenset({StateFactAuthority.PROVIDER, StateFactAuthority.TELEMETRY}),
    StateFactLane.DERIVED: frozenset({StateFactAuthority.DETERMINISTIC_FUNCTION}),
    StateFactLane.DESIRED: frozenset({StateFactAuthority.APPROVED_POLICY}),
    StateFactLane.EXECUTION: frozenset({StateFactAuthority.EXECUTION_LEDGER}),
}


@dataclass(frozen=True, slots=True)
class StateFactMetadata:
    """Canonical authority, time, freshness, and provenance for one state fact."""

    lane: StateFactLane
    authority: StateFactAuthority
    source_identity: str
    source_revision: str
    effective_at: datetime
    recorded_at: datetime
    evidence_cutoff: datetime
    freshness_ceiling_seconds: int
    completeness: float
    synthetic: bool
    conflicts: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.authority not in _LANE_AUTHORITIES[self.lane]:
            raise ValueError(
                f"state fact authority {self.authority.value!r} is invalid for "
                f"{self.lane.value!r} lane"
            )
        for field_name, string_value in (
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
        ):
            if not string_value.strip():
                raise ValueError(f"StateFactMetadata.{field_name} MUST be non-empty")
        for field_name, timestamp in (
            ("effective_at", self.effective_at),
            ("recorded_at", self.recorded_at),
            ("evidence_cutoff", self.evidence_cutoff),
        ):
            if timestamp.tzinfo is None:
                raise ValueError(f"StateFactMetadata.{field_name} MUST be timezone-aware")
        if self.effective_at > self.evidence_cutoff:
            raise ValueError("StateFactMetadata.effective_at MUST NOT exceed evidence_cutoff")
        if self.evidence_cutoff > self.recorded_at:
            raise ValueError("StateFactMetadata.evidence_cutoff MUST NOT exceed recorded_at")
        if isinstance(self.freshness_ceiling_seconds, bool) or not isinstance(
            self.freshness_ceiling_seconds, int
        ):
            raise ValueError("StateFactMetadata.freshness_ceiling_seconds MUST be an integer")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("StateFactMetadata.freshness_ceiling_seconds MUST be >= 1")
        if isinstance(self.completeness, bool) or not isinstance(self.completeness, (int, float)):
            raise ValueError("StateFactMetadata.completeness MUST be numeric")
        if not 0.0 <= self.completeness <= 1.0:
            raise ValueError("StateFactMetadata.completeness MUST be between 0 and 1")
        if not isinstance(self.synthetic, bool):
            raise ValueError("StateFactMetadata.synthetic MUST be a boolean")
        canonical_conflicts = _canonical_refs(
            self.conflicts,
            field_name="conflicts",
            required=False,
        )
        canonical_evidence = _canonical_refs(
            self.evidence_refs,
            field_name="evidence_refs",
            required=True,
        )
        object.__setattr__(self, "conflicts", canonical_conflicts)
        object.__setattr__(self, "evidence_refs", canonical_evidence)

    def to_mapping(self) -> dict[str, object]:
        """Return the stable JSON-compatible property representation."""

        return {
            "authority": self.authority.value,
            "completeness": self.completeness,
            "conflicts": list(self.conflicts),
            "effective_at": _timestamp(self.effective_at),
            "evidence_cutoff": _timestamp(self.evidence_cutoff),
            "evidence_refs": list(self.evidence_refs),
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "lane": self.lane.value,
            "recorded_at": _timestamp(self.recorded_at),
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "synthetic": self.synthetic,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Decode the exact canonical property shape or reject malformed evidence."""

        _require_keys(
            value,
            {
                "authority",
                "completeness",
                "conflicts",
                "effective_at",
                "evidence_cutoff",
                "evidence_refs",
                "freshness_ceiling_seconds",
                "lane",
                "recorded_at",
                "source_identity",
                "source_revision",
                "synthetic",
            },
            name="state fact metadata",
        )
        completeness = value["completeness"]
        freshness_ceiling = value["freshness_ceiling_seconds"]
        synthetic = value["synthetic"]
        if isinstance(completeness, bool) or not isinstance(completeness, (int, float)):
            raise ValueError("state fact metadata completeness MUST be numeric")
        if isinstance(freshness_ceiling, bool) or not isinstance(freshness_ceiling, int):
            raise ValueError("state fact metadata freshness ceiling MUST be an integer")
        if not isinstance(synthetic, bool):
            raise ValueError("state fact metadata synthetic MUST be a boolean")
        return cls(
            lane=StateFactLane(_string(value, "lane")),
            authority=StateFactAuthority(_string(value, "authority")),
            source_identity=_string(value, "source_identity"),
            source_revision=_string(value, "source_revision"),
            effective_at=_parse_timestamp(value, "effective_at"),
            recorded_at=_parse_timestamp(value, "recorded_at"),
            evidence_cutoff=_parse_timestamp(value, "evidence_cutoff"),
            freshness_ceiling_seconds=freshness_ceiling,
            completeness=float(completeness),
            synthetic=synthetic,
            conflicts=_string_tuple(value, "conflicts"),
            evidence_refs=_string_tuple(value, "evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class LinkObservationMetadata:
    """Typed observation and independent verification state for one inventory link."""

    state_fact: StateFactMetadata
    verification_method: str
    verified: bool
    verifier_identity: str | None = None
    verifier_revision: str | None = None
    verification_receipt_ref: str | None = None
    inventory_generation: str | None = None
    mapping_id: str | None = None
    mapping_revision: str | None = None
    source_schema_version: str | None = None
    source_schema_digest: str | None = None

    def __post_init__(self) -> None:
        if self.state_fact.lane not in {StateFactLane.OBSERVED, StateFactLane.DERIVED}:
            raise ValueError("link observation state fact MUST be observed or derived")
        if not self.verification_method.strip():
            raise ValueError("LinkObservationMetadata.verification_method MUST be non-empty")
        verifier_values = (
            self.verifier_identity,
            self.verifier_revision,
            self.verification_receipt_ref,
        )
        if self.verified and (
            self.verification_receipt_ref is None or not self.verification_receipt_ref.strip()
        ):
            raise ValueError("verified link observation MUST identify verification receipt")
        if self.verified and any(value is None or not value.strip() for value in verifier_values):
            raise ValueError("verified link observation MUST identify verifier and revision")
        if not self.verified and any(value is not None for value in verifier_values):
            raise ValueError("unverified link observation MUST NOT claim verifier metadata")
        if self.verified and self.verification_method not in TRUSTED_LINK_VERIFICATION_METHODS:
            raise ValueError("verified link observation MUST use a trusted verification method")
        if self.verified and (
            self.state_fact.source_identity.strip().casefold()
            == str(self.verifier_identity).strip().casefold()
        ):
            raise ValueError("verified link observation MUST identify an independent verifier")
        if self.verified and self.state_fact.conflicts:
            raise ValueError("conflicting link observation MUST NOT be marked verified")
        mapping_values = (
            self.inventory_generation,
            self.mapping_id,
            self.mapping_revision,
            self.source_schema_version,
            self.source_schema_digest,
        )
        if any(value is not None for value in mapping_values) and any(
            value is None or not value.strip() for value in mapping_values
        ):
            raise ValueError(
                "provider relationship metadata MUST identify generation, mapping, and schema"
            )

    def to_mapping(self) -> dict[str, object]:
        """Return the stable JSON-compatible property representation."""

        return {
            "state_fact": self.state_fact.to_mapping(),
            "verification_method": self.verification_method,
            "verified": self.verified,
            "verifier_identity": self.verifier_identity,
            "verifier_revision": self.verifier_revision,
            "verification_receipt_ref": self.verification_receipt_ref,
            "inventory_generation": self.inventory_generation,
            "mapping_id": self.mapping_id,
            "mapping_revision": self.mapping_revision,
            "source_schema_version": self.source_schema_version,
            "source_schema_digest": self.source_schema_digest,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        """Decode the exact canonical property shape or reject malformed evidence."""

        expected = {
            "state_fact",
            "verification_method",
            "verified",
            "verifier_identity",
            "verifier_revision",
            "verification_receipt_ref",
            "inventory_generation",
            "mapping_id",
            "mapping_revision",
            "source_schema_version",
            "source_schema_digest",
        }
        prior_expected = expected - {
            "inventory_generation",
            "mapping_id",
            "mapping_revision",
            "source_schema_version",
            "source_schema_digest",
        }
        canonical_without_receipt = expected - {"verification_receipt_ref"}
        legacy_expected = prior_expected - {"verification_receipt_ref"}
        if set(value) not in {
            frozenset(expected),
            frozenset(canonical_without_receipt),
            frozenset(prior_expected),
            frozenset(legacy_expected),
        }:
            raise ValueError(
                "link observation metadata MUST contain the canonical or legacy verification shape"
            )
        raw_state_fact = value["state_fact"]
        raw_verified = value["verified"]
        if not isinstance(raw_state_fact, Mapping):
            raise ValueError("link observation state_fact MUST be an object")
        if not isinstance(raw_verified, bool):
            raise ValueError("link observation verified MUST be a boolean")
        has_receipt = "verification_receipt_ref" in value
        verified = raw_verified and has_receipt
        return cls(
            state_fact=StateFactMetadata.from_mapping(raw_state_fact),
            verification_method=_string(value, "verification_method"),
            verified=verified,
            verifier_identity=(_optional_string(value, "verifier_identity") if verified else None),
            verifier_revision=(_optional_string(value, "verifier_revision") if verified else None),
            verification_receipt_ref=(
                _optional_string(value, "verification_receipt_ref") if verified else None
            ),
            inventory_generation=(
                _optional_string(value, "inventory_generation")
                if "inventory_generation" in value
                else None
            ),
            mapping_id=(_optional_string(value, "mapping_id") if "mapping_id" in value else None),
            mapping_revision=(
                _optional_string(value, "mapping_revision") if "mapping_revision" in value else None
            ),
            source_schema_version=(
                _optional_string(value, "source_schema_version")
                if "source_schema_version" in value
                else None
            ),
            source_schema_digest=(
                _optional_string(value, "source_schema_digest")
                if "source_schema_digest" in value
                else None
            ),
        )


def _canonical_refs(values: tuple[str, ...], *, field_name: str, required: bool) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"StateFactMetadata.{field_name} MUST contain non-empty values")
    canonical = tuple(sorted(set(values)))
    if required and not canonical:
        raise ValueError(f"StateFactMetadata.{field_name} MUST be non-empty")
    return canonical


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Mapping[str, Any], field_name: str) -> datetime:
    raw = _string(value, field_name)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"state fact metadata {field_name} MUST be RFC 3339") from exc


def _require_keys(value: Mapping[str, Any], expected: set[str], *, name: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} MUST contain exactly {sorted(expected)!r}")


def _string(value: Mapping[str, Any], field_name: str) -> str:
    raw = value[field_name]
    if not isinstance(raw, str):
        raise ValueError(f"metadata {field_name} MUST be a string")
    return raw


def _optional_string(value: Mapping[str, Any], field_name: str) -> str | None:
    raw = value[field_name]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"metadata {field_name} MUST be a string or null")
    return raw


def _string_tuple(value: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    raw = value[field_name]
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError(f"metadata {field_name} MUST be an array of strings")
    return tuple(raw)


__all__ = [
    "LINK_OBSERVATION_METADATA_PROPERTY",
    "STATE_FACT_METADATA_PROPERTY",
    "TRUSTED_LINK_VERIFICATION_METHODS",
    "LinkObservationMetadata",
    "StateFactAuthority",
    "StateFactLane",
    "StateFactMetadata",
]
