"""Provider-neutral contracts for autonomous rule-discovery cycles."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROPOSAL_KINDS = frozenset(
    {"new", "new-scenario", "revision", "retirement", "threshold_adjustment"}
)
_AUTHORITY_FIELDS = frozenset(
    {
        "approval",
        "approved",
        "execution_authority",
        "mode",
        "promoted",
        "promotion_state",
    }
)


class DiscoverySignalKind(StrEnum):
    """Normalized feed kinds admitted by the discovery observe stage."""

    UPSTREAM = "upstream"
    OPERATIONAL = "operational"
    OVERRIDE = "override"
    CATALOG = "catalog"


class DiscoveryCandidateState(StrEnum):
    """Terminal disposition for one candidate inside a completed cycle."""

    INTEGRATED = "integrated"
    HELD = "held"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DiscoverySignal:
    """One bounded, normalized observation supplied to both model families."""

    signal_id: str
    kind: DiscoverySignalKind
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    facts: Mapping[str, object]

    def __post_init__(self) -> None:
        require_identifier(self.signal_id, "signal_id")
        require_aware(self.observed_at, "observed_at")
        if not 1 <= len(self.evidence_refs) <= 64:
            raise ValueError("discovery signal evidence_refs MUST contain 1 to 64 entries")
        if any(not value or len(value) > 512 for value in self.evidence_refs):
            raise ValueError("discovery signal evidence refs MUST be non-empty and bounded")
        canonical_mapping(self.facts, "discovery signal facts", maximum_bytes=64 * 1024)


@dataclass(frozen=True, slots=True)
class DiscoveryObservationBatch:
    """One complete bounded observation window."""

    window_start: datetime
    window_end: datetime
    signals: tuple[DiscoverySignal, ...]
    complete: bool

    def __post_init__(self) -> None:
        require_aware(self.window_start, "window_start")
        require_aware(self.window_end, "window_end")
        if self.window_end < self.window_start:
            raise ValueError("discovery observation window MUST not be inverted")
        if not isinstance(self.complete, bool):
            raise ValueError("discovery observation completeness MUST be boolean")
        identities = {signal.signal_id for signal in self.signals}
        if len(identities) != len(self.signals):
            raise ValueError("discovery observation signal ids MUST be unique")


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    """One inert rule candidate proposed by the primary discovery model."""

    proposal_kind: str
    target_rule_id: str
    source_signal_ids: tuple[str, ...]
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.proposal_kind not in _PROPOSAL_KINDS:
            raise ValueError("discovery candidate proposal_kind is unsupported")
        require_identifier(self.target_rule_id, "target_rule_id")
        if not self.source_signal_ids or len(self.source_signal_ids) > 64:
            raise ValueError("discovery candidate source_signal_ids MUST contain 1 to 64 entries")
        if len(set(self.source_signal_ids)) != len(self.source_signal_ids):
            raise ValueError("discovery candidate source_signal_ids MUST be unique")
        if _contains_authority_field(self.payload):
            raise ValueError("discovery candidate payload MUST NOT carry authority fields")
        canonical_mapping(self.payload, "discovery candidate payload", maximum_bytes=256 * 1024)

    @property
    def digest(self) -> str:
        """Return the replay-stable candidate identity."""

        return digest(
            {
                "proposal_kind": self.proposal_kind,
                "target_rule_id": self.target_rule_id,
                "source_signal_ids": self.source_signal_ids,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscoveryModelReview:
    """One independent-family approval or disagreement."""

    candidate_digest: str
    approved: bool
    reason: str

    def __post_init__(self) -> None:
        require_digest(self.candidate_digest, "candidate_digest")
        if not isinstance(self.approved, bool):
            raise ValueError("discovery model review approved MUST be boolean")
        require_reason(self.reason)


@dataclass(frozen=True, slots=True)
class DiscoveryVerificationReceipt:
    """Deterministic quality-gate result for one agreed candidate."""

    candidate_digest: str
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        require_digest(self.candidate_digest, "candidate_digest")
        if not isinstance(self.passed, bool):
            raise ValueError("discovery verification passed MUST be boolean")
        require_reason(self.reason)


@dataclass(frozen=True, slots=True)
class DiscoveryIntegrationReceipt:
    """Idempotent inert-review publication result."""

    candidate_digest: str
    review_ref: str
    already_existed: bool

    def __post_init__(self) -> None:
        require_digest(self.candidate_digest, "candidate_digest")
        if not self.review_ref or len(self.review_ref) > 512:
            raise ValueError("discovery integration review_ref MUST be non-empty and bounded")
        if not isinstance(self.already_existed, bool):
            raise ValueError("discovery integration already_existed MUST be boolean")


@dataclass(frozen=True, slots=True)
class DiscoveryCycleMetrics:
    """Governed throughput metrics for one completed cycle."""

    candidates_per_cycle: int
    gate_pass_rate: float
    override_trigger_rate: float
    retirement_rate: float

    def __post_init__(self) -> None:
        if self.candidates_per_cycle < 0:
            raise ValueError("candidates_per_cycle MUST be non-negative")
        for value in (self.gate_pass_rate, self.override_trigger_rate, self.retirement_rate):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("discovery metric rates MUST be finite values in [0, 1]")

    def to_mapping(self) -> dict[str, object]:
        return {
            "candidates_per_cycle": self.candidates_per_cycle,
            "gate_pass_rate": self.gate_pass_rate,
            "override_trigger_rate": self.override_trigger_rate,
            "retirement_rate": self.retirement_rate,
        }


@dataclass(frozen=True, slots=True)
class DiscoveryCandidateDecision:
    """Terminal candidate state retained for replay and human review."""

    candidate_digest: str
    state: DiscoveryCandidateState
    reason: str
    review_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryCycleReport:
    """Replay-safe result of one scheduled discovery cycle."""

    cycle_id: str
    status: str
    signal_count: int
    decisions: tuple[DiscoveryCandidateDecision, ...]
    metrics: DiscoveryCycleMetrics | None
    replayed: bool = False
    failure_kind: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryCycleConfig:
    """Bounds and retention for the mechanical scheduler."""

    schedule_id: str = "rule-catalog-autonomous-discovery"
    interval_seconds: int = 3600
    max_signals: int = 5_000
    max_candidates: int = 500
    timeout_seconds: float = 300.0
    retain_cycles: int = 1_000

    def __post_init__(self) -> None:
        require_identifier(self.schedule_id, "schedule_id")
        if (
            min(
                self.interval_seconds,
                self.max_signals,
                self.max_candidates,
                self.retain_cycles,
            )
            < 1
        ):
            raise ValueError("discovery cycle integer bounds MUST be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("discovery cycle timeout_seconds MUST be finite and positive")


@runtime_checkable
class DiscoverySignalSource(Protocol):
    """Load one complete normalized window without changing source state."""

    async def observe(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> DiscoveryObservationBatch: ...


@runtime_checkable
class DiscoveryHypothesisModel(Protocol):
    """Primary off-path T2 model that proposes inert candidates."""

    @property
    def model_identity(self) -> str: ...

    @property
    def model_family(self) -> str: ...

    async def hypothesize(
        self,
        batch: DiscoveryObservationBatch,
    ) -> tuple[DiscoveryCandidate, ...]: ...


@runtime_checkable
class DiscoveryCrossCheckModel(Protocol):
    """Independent-family model that re-approves one canonical candidate."""

    @property
    def model_identity(self) -> str: ...

    @property
    def model_family(self) -> str: ...

    async def review(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryModelReview: ...


@runtime_checkable
class DiscoveryCandidateVerifier(Protocol):
    """Run deterministic schema, provenance, replay, policy, and shadow checks."""

    async def verify(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryVerificationReceipt: ...


@runtime_checkable
class DiscoveryCandidateIntegrator(Protocol):
    """Publish an inert, review-required catalog package idempotently."""

    async def integrate(
        self,
        candidate: DiscoveryCandidate,
        receipt: DiscoveryVerificationReceipt,
    ) -> DiscoveryIntegrationReceipt: ...


def canonical_mapping(
    value: Mapping[str, object],
    label: str,
    *,
    maximum_bytes: int,
) -> str:
    """Serialize a bounded mapping for replay identity."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} MUST be canonical JSON") from exc
    if len(encoded.encode()) > maximum_bytes:
        raise ValueError(f"{label} exceeds its byte limit")
    return encoded


def _contains_authority_field(value: object) -> bool:
    stack = [value]
    visited: set[int] = set()
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            if any(key in _AUTHORITY_FIELDS for key in item if isinstance(key, str)):
                return True
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            identity = id(item)
            if identity in visited:
                continue
            visited.add(identity)
            stack.extend(item)
    return False


def digest(value: Mapping[str, object]) -> str:
    """Hash one bounded canonical discovery record."""

    return hashlib.sha256(
        canonical_mapping(value, "discovery digest input", maximum_bytes=512 * 1024).encode()
    ).hexdigest()


def require_identifier(value: str, label: str) -> None:
    if not value or len(value) > 128 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} MUST be a bounded canonical identifier")


def require_digest(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} MUST be lowercase SHA-256")


def require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} MUST be timezone-aware")


def require_reason(value: str) -> None:
    if not value or len(value) > 256 or not value.isascii():
        raise ValueError("discovery decision reason MUST be bounded ASCII")


__all__ = [
    "DiscoveryCandidate",
    "DiscoveryCandidateDecision",
    "DiscoveryCandidateIntegrator",
    "DiscoveryCandidateState",
    "DiscoveryCandidateVerifier",
    "DiscoveryCrossCheckModel",
    "DiscoveryCycleConfig",
    "DiscoveryCycleMetrics",
    "DiscoveryCycleReport",
    "DiscoveryHypothesisModel",
    "DiscoveryIntegrationReceipt",
    "DiscoveryModelReview",
    "DiscoveryObservationBatch",
    "DiscoverySignal",
    "DiscoverySignalKind",
    "DiscoverySignalSource",
    "DiscoveryVerificationReceipt",
]
