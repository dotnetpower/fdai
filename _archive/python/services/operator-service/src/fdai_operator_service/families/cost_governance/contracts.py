"""Dependency contracts for the Operator Cost Governance family."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts import (
    CostAccessGrant,
    CostAnalyticsProjection,
    CostAnalyticsRunReceipt,
    CostDecisionCaseProjection,
    CostDisclosureCeiling,
    CostEvidenceSourceFacet,
    CostGovernanceUnavailableReason,
    CostProjectionRecord,
    CostSettlementOutcomeProjection,
)

COST_DISCLOSURE_RETENTION_DAYS = 400
COST_DISCLOSURE_PURGE_GRACE_DAYS = 30


def decode_cost_pseudonym_key(value: str | None) -> bytes | None:
    """Decode one persisted 256-bit hexadecimal key or fail closed."""

    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if (
        len(normalized) != 64
        or normalized != normalized.casefold()
        or any(character not in "0123456789abcdef" for character in normalized)
    ):
        raise ValueError("FDAI_COST_PSEUDONYM_KEY MUST be 64 lowercase hexadecimal characters")
    return bytes.fromhex(normalized)


@dataclass(frozen=True, slots=True)
class CostActivationSnapshot:
    """Persisted manager-derived activation state read without reinterpretation."""

    vertical_id: str
    package_id: str
    available: bool
    enabled: bool
    availability_reasons: tuple[str, ...]
    package_version: str
    image_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    ontology_release_digest: str
    revision: int

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.availability_reasons)))
        object.__setattr__(self, "availability_reasons", reasons)
        if len(reasons) > 32 or any(
            not reason.isascii() or not 1 <= len(reason) <= 256 for reason in reasons
        ):
            raise ValueError("availability reasons must be bounded non-empty ASCII")
        if self.available == bool(reasons):
            raise ValueError("available must match empty availability reasons")
        if self.enabled and not self.available:
            raise ValueError("unavailable Cost Governance cannot be enabled")


@dataclass(frozen=True, slots=True)
class CostAccessDecision:
    """One server-owned grant decision and deployment disclosure ceiling."""

    grant: CostAccessGrant | None
    ceiling: CostDisclosureCeiling | None
    reason: CostGovernanceUnavailableReason | None = None


@dataclass(frozen=True, slots=True)
class CostDisclosureAuditRecord:
    """Content-free proof that one authorized disclosure completed."""

    decision_id: str
    principal_digest: str
    scope_digest: str
    surface: str
    grant_revision: int
    ceiling_revision: int
    activation_revision: int
    disclosure_digest: str
    record_count: int
    suppressed_count: int
    occurred_at: datetime
    retention_until: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None

    def __post_init__(self) -> None:
        digests = (
            self.decision_id,
            self.principal_digest,
            self.scope_digest,
            self.disclosure_digest,
        )
        if any(
            len(value) != 71
            or not value.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in value[7:])
            for value in digests
        ):
            raise ValueError("Cost disclosure audit digests MUST use sha256:<digest>")
        if not self.surface or not self.surface.isascii() or len(self.surface) > 64:
            raise ValueError("Cost disclosure audit surface MUST be bounded ASCII")
        counts = (
            self.grant_revision,
            self.ceiling_revision,
            self.activation_revision,
            self.record_count,
            self.suppressed_count,
        )
        if any(value < 0 for value in counts) or self.suppressed_count > self.record_count:
            raise ValueError("Cost disclosure audit counts MUST be nonnegative and bounded")
        for name, value in (
            ("occurred_at", self.occurred_at),
            ("retention_until", self.retention_until),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Cost disclosure audit {name} MUST be timezone-aware")
        if self.retention_until <= self.occurred_at:
            raise ValueError("Cost disclosure retention MUST follow occurrence")
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("Cost disclosure legal hold state and reference MUST match")
        if self.legal_hold_ref is not None and (
            not self.legal_hold_ref.isascii() or not 1 <= len(self.legal_hold_ref) <= 512
        ):
            raise ValueError("Cost disclosure legal hold reference MUST be bounded ASCII")


@dataclass(frozen=True, slots=True)
class CostProjectionEvidenceSnapshot:
    """Authoritative persisted inputs used to compute public readiness."""

    window_start_at: datetime | None
    window_end_at: datetime | None
    latest_source_at: datetime | None
    complete_count: int
    partial_count: int
    sources: tuple[CostEvidenceSourceFacet, ...]
    latest_analytics_run: CostAnalyticsRunReceipt | None
    resource_candidate_count: int
    incomplete_candidate_count: int
    decision_case_count: int
    incomplete_decision_case_count: int
    settlement_count: int
    incomplete_settlement_count: int


@dataclass(frozen=True, slots=True)
class CostAnalyticsSnapshot:
    """One immutable analytics payload bound to its exact persisted scope."""

    snapshot_id: str
    scope_id: str
    projection: CostAnalyticsProjection

    def __post_init__(self) -> None:
        if (
            len(self.snapshot_id) != 74
            or not self.snapshot_id.startswith("analytics:")
            or any(character not in "0123456789abcdef" for character in self.snapshot_id[10:])
        ):
            raise ValueError("Cost Analytics snapshot id MUST use analytics:<sha256>")
        if not self.scope_id or self.scope_id == "*" or len(self.scope_id) > 1024:
            raise ValueError("Cost Analytics snapshot scope MUST be exact and bounded")


class CostAccessReader(Protocol):
    """Read one user-specific grant before any activation or cost-table query."""

    async def read_access(
        self,
        *,
        principal_id: str,
        purpose: str,
        scope: str,
        now: datetime,
    ) -> CostAccessDecision: ...


class CostActivationReader(Protocol):
    """Read the authoritative package activation snapshot."""

    async def read_activation(self, package_id: str) -> CostActivationSnapshot | None: ...


class CostActivationWriter(Protocol):
    """Apply one audited, revision-fenced package enablement preference."""

    async def set_enabled(
        self,
        *,
        package_id: str,
        actor_id: str,
        enabled: bool,
        expected_revision: int,
        request_id: str,
    ) -> CostActivationSnapshot: ...


class CostProjectionReader(Protocol):
    """Read retained observations and explicit authority-free lineage projections."""

    async def read_records(
        self,
        *,
        surface: str,
        scope: str,
        limit: int,
    ) -> tuple[CostProjectionRecord, ...]: ...

    async def read_projection_evidence(
        self,
        *,
        scope: str,
        analytics_snapshot_id: str | None,
    ) -> CostProjectionEvidenceSnapshot: ...

    async def read_decision_cases(
        self,
        *,
        scope: str,
        limit: int,
        pseudonym_key: bytes,
    ) -> tuple[CostDecisionCaseProjection, ...]: ...

    async def read_settlement_outcomes(
        self,
        *,
        scope: str,
        limit: int,
        pseudonym_key: bytes,
    ) -> tuple[CostSettlementOutcomeProjection, ...]: ...


class CostAnalyticsReader(Protocol):
    """Read the latest disclosure-safe analytics snapshot for one scope."""

    async def read_analytics(self, *, scope: str) -> CostAnalyticsSnapshot | None: ...


class CostDisclosureAuditWriter(Protocol):
    """Append one authorized delivery proof before returning cost data."""

    async def append_disclosure_audit(self, record: CostDisclosureAuditRecord) -> None: ...


__all__ = [
    "COST_DISCLOSURE_PURGE_GRACE_DAYS",
    "COST_DISCLOSURE_RETENTION_DAYS",
    "CostAccessDecision",
    "CostAccessReader",
    "CostAnalyticsSnapshot",
    "CostAnalyticsReader",
    "CostActivationReader",
    "CostActivationSnapshot",
    "CostActivationWriter",
    "CostDisclosureAuditRecord",
    "CostDisclosureAuditWriter",
    "CostProjectionReader",
    "CostProjectionEvidenceSnapshot",
    "decode_cost_pseudonym_key",
]
