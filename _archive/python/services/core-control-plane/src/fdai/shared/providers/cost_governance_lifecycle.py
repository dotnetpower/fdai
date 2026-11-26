"""Authority-neutral exact-revision Cost Governance lifecycle evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class CostEvidenceKind(StrEnum):
    """Evidence provenance classes that never change authority."""

    LIVE_AUTHORITATIVE = "live-authoritative"
    SYNTHETIC = "synthetic"
    FIXTURE = "fixture"
    UNIT = "unit"


class CostLifecycleOperation(StrEnum):
    """Versioned package lifecycle operations."""

    INSTALL = "install"
    ENABLE = "enable"
    DISABLE = "disable"
    UPGRADE = "upgrade"
    ROLLBACK = "rollback"


class CostLifecycleOutcome(StrEnum):
    """Terminal lifecycle operation outcomes."""

    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CostRevisionPin:
    """Exact package, source, ontology, and runtime identity for one campaign."""

    package_id: str
    package_version: str
    source_revision: str
    wheel_digest: str
    image_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    ontology_release_digest: str
    runtime_config_digest: str
    activation_revision: int

    def __post_init__(self) -> None:
        for name in ("package_id",):
            _bounded_text(name, getattr(self, name))
        if _VERSION.fullmatch(self.package_version) is None:
            raise ValueError("package_version MUST use MAJOR.MINOR.PATCH")
        if _SOURCE_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("source_revision MUST be an exact 40-character revision")
        for name in (
            "wheel_digest",
            "image_digest",
            "asset_manifest_digest",
            "semantic_profile_digest",
            "ontology_release_digest",
            "runtime_config_digest",
        ):
            _require_digest(name, getattr(self, name))
        if self.activation_revision < 1:
            raise ValueError("activation_revision MUST be positive")

    @property
    def digest(self) -> str:
        """Return the canonical immutable revision identity."""

        return _canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return stable machine fields used by receipts and campaign evidence."""

        return {
            "activation_revision": self.activation_revision,
            "asset_manifest_digest": self.asset_manifest_digest,
            "image_digest": self.image_digest,
            "ontology_release_digest": self.ontology_release_digest,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "runtime_config_digest": self.runtime_config_digest,
            "semantic_profile_digest": self.semantic_profile_digest,
            "source_revision": self.source_revision,
            "wheel_digest": self.wheel_digest,
        }


@dataclass(frozen=True, slots=True)
class CostLifecycleReceipt:
    """Append-only lifecycle result bound to one exact revision and evidence kind."""

    schema_version: str
    receipt_id: str
    idempotency_key: str
    operation: CostLifecycleOperation
    outcome: CostLifecycleOutcome
    revision_pin: CostRevisionPin
    available: bool
    enabled: bool
    occurred_at: datetime
    evidence_kind: CostEvidenceKind
    evidence_refs: tuple[str, ...]
    retention_until: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("lifecycle receipt schema_version MUST be 1.0.0")
        _bounded_text("receipt_id", self.receipt_id)
        _bounded_text("idempotency_key", self.idempotency_key)
        _aware("occurred_at", self.occurred_at)
        _aware("retention_until", self.retention_until)
        if self.occurred_at >= self.retention_until:
            raise ValueError("lifecycle receipt retention MUST follow occurrence")
        if self.legal_hold != (self.legal_hold_ref is not None):
            raise ValueError("lifecycle receipt legal hold and reference MUST agree")
        if self.legal_hold_ref is not None:
            _bounded_text("legal_hold_ref", self.legal_hold_ref)
        refs = _evidence_refs(self.evidence_refs)
        object.__setattr__(self, "evidence_refs", refs)
        if self.outcome is CostLifecycleOutcome.SUCCEEDED:
            if (
                self.operation
                in {
                    CostLifecycleOperation.INSTALL,
                    CostLifecycleOperation.DISABLE,
                }
                and self.enabled
            ):
                raise ValueError("successful install or disable receipt MUST be disabled")
            if self.operation is CostLifecycleOperation.ENABLE and (
                not self.available or not self.enabled
            ):
                raise ValueError("successful enable receipt MUST be available and enabled")

    @property
    def digest(self) -> str:
        """Return the tamper-evident canonical receipt digest."""

        return _canonical_digest(self.to_mapping())

    def verify_digest(self, expected_digest: str) -> bool:
        """Verify a supplied persisted digest without changing receipt meaning."""

        _require_digest("expected_digest", expected_digest)
        return self.digest == expected_digest

    def to_mapping(self) -> dict[str, object]:
        """Return the versioned canonical receipt payload."""

        return {
            "available": self.available,
            "enabled": self.enabled,
            "evidence_kind": self.evidence_kind.value,
            "evidence_refs": list(self.evidence_refs),
            "idempotency_key": self.idempotency_key,
            "legal_hold": self.legal_hold,
            "legal_hold_ref": self.legal_hold_ref,
            "occurred_at": self.occurred_at.isoformat(),
            "operation": self.operation.value,
            "outcome": self.outcome.value,
            "receipt_id": self.receipt_id,
            "retention_until": self.retention_until.isoformat(),
            "revision_pin": self.revision_pin.to_mapping(),
            "schema_version": self.schema_version,
        }


class CostLifecycleReceiptStore(Protocol):
    """Append and read exact lifecycle receipts without activation authority."""

    async def append_cost_lifecycle_receipt(
        self,
        receipt: CostLifecycleReceipt,
        *,
        expected_receipt_digest: str,
    ) -> bool: ...

    async def read_cost_lifecycle_receipts(
        self,
        package_id: str,
        *,
        limit: int,
    ) -> tuple[CostLifecycleReceipt, ...]: ...


def _bounded_text(name: str, value: str) -> None:
    if not value or not value.isascii() or len(value) > 512:
        raise ValueError(f"{name} MUST be bounded non-empty ASCII")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST use sha256:<digest>")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _evidence_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    refs = tuple(dict.fromkeys(values))
    if not 1 <= len(refs) <= 64:
        raise ValueError("evidence_refs MUST contain 1..64 unique values")
    for value in refs:
        _bounded_text("evidence_ref", value)
    return refs


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CostEvidenceKind",
    "CostLifecycleOperation",
    "CostLifecycleOutcome",
    "CostLifecycleReceipt",
    "CostLifecycleReceiptStore",
    "CostRevisionPin",
]
