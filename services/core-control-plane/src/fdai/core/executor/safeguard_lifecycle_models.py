"""Result, disposition, and configuration records for the safeguard lifecycle.

Every record here is evidence returned to a caller. None of it grants
execution or effect-verification authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from fdai.core.executor.post_release_closure_store import PostReleaseClosureStoreReceipt
from fdai.core.executor.safeguard_evidence_lifecycle import SafeguardEvidenceLifecycleResult

_SOURCE_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")


@runtime_checkable
class ProductionSafeguardStore(Protocol):
    """Marker implemented only by durable production lifecycle stores."""

    @property
    def production_eligible(self) -> bool:
        """Whether the store is durable and safe for production composition."""
        ...


class SafeguardCoordinationDisposition(StrEnum):
    """Caller-facing result without granting execution authority."""

    COMPLETED = "completed"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


class SafeguardCoordinationError(RuntimeError):
    """A required lifecycle phase failed before a safe dispatch result existed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SafeguardCoordinatedDispatchResult:
    """Final bundle and closure evidence returned to a real executor."""

    disposition: SafeguardCoordinationDisposition
    bundle_digest: str | None
    lifecycle: SafeguardEvidenceLifecycleResult | None
    closure_receipt: PostReleaseClosureStoreReceipt | None
    dispatch_performed: bool
    reason: str | None = None
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("safeguard coordinated result MUST NOT grant authority")
        if self.dispatch_performed and self.bundle_digest is None:
            raise ValueError("a performed dispatch requires a finalized bundle digest")


@dataclass(frozen=True, slots=True)
class SafeguardLifecycleCoordinatorConfig:
    """Immutable production identity, timing, and trust configuration."""

    source_revision: str
    producer_id: str
    producer_version: str
    actor: str
    expected_lock_verifier_id: str
    expected_lock_verifier_version: str
    expected_lock_trust_anchor_id: str
    reservation_lease: timedelta = timedelta(minutes=5)
    production: bool = False

    def __post_init__(self) -> None:
        if _SOURCE_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("safeguard lifecycle source revision MUST be canonical")
        for name, value in (
            ("producer_id", self.producer_id),
            ("producer_version", self.producer_version),
            ("actor", self.actor),
            ("expected_lock_verifier_id", self.expected_lock_verifier_id),
            ("expected_lock_verifier_version", self.expected_lock_verifier_version),
            ("expected_lock_trust_anchor_id", self.expected_lock_trust_anchor_id),
        ):
            if not value.strip() or value != value.strip() or len(value) > 512:
                raise ValueError(f"safeguard lifecycle {name} MUST be canonical and bounded")
        if self.reservation_lease <= timedelta(0):
            raise ValueError("safeguard lifecycle reservation lease MUST be positive")


__all__ = [
    "ProductionSafeguardStore",
    "SafeguardCoordinatedDispatchResult",
    "SafeguardCoordinationDisposition",
    "SafeguardCoordinationError",
    "SafeguardLifecycleCoordinatorConfig",
]
