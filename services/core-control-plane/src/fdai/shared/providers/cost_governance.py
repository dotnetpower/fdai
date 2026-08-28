"""CSP-neutral contracts for optional Cost Governance packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

COST_SAMPLE_EVENT_TYPE = "specialist.cost_sample"
_DIGEST_PREFIX = "sha256:"


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} MUST be non-empty")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class CostPackageActivation:
    """Authoritative revisioned package-activation read model."""

    vertical_id: str
    package_id: str
    available: bool
    enabled: bool
    availability_reasons: tuple[str, ...]
    package_version: str
    image_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    revision: int
    effective_at: datetime
    ontology_release_id: str
    ontology_release_digest: str
    source_authority: str
    previously_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "vertical_id",
            "package_id",
            "package_version",
            "image_digest",
            "asset_manifest_digest",
            "semantic_profile_digest",
            "ontology_release_id",
            "ontology_release_digest",
            "source_authority",
        ):
            _require_text(name, str(getattr(self, name)))
        if self.revision < 0:
            raise ValueError("activation revision MUST be nonnegative")
        reasons = tuple(sorted(set(self.availability_reasons)))
        object.__setattr__(self, "availability_reasons", reasons)
        if len(reasons) > 32 or any(
            not reason.isascii() or not 1 <= len(reason) <= 256 for reason in reasons
        ):
            raise ValueError("availability reasons MUST be bounded non-empty ASCII")
        if self.available == bool(reasons):
            raise ValueError("available MUST be true exactly when availability reasons are empty")
        if self.enabled and not self.available:
            raise ValueError("an unavailable package MUST NOT be enabled")
        for name in (
            "image_digest",
            "asset_manifest_digest",
            "semantic_profile_digest",
            "ontology_release_digest",
        ):
            value = str(getattr(self, name))
            if not value.startswith(_DIGEST_PREFIX) or len(value) != 71:
                raise ValueError(f"{name} MUST use sha256:<digest>")
            try:
                int(value.removeprefix(_DIGEST_PREFIX), 16)
            except ValueError as exc:
                raise ValueError(f"{name} MUST use sha256:<digest>") from exc
        _require_aware("effective_at", self.effective_at)

    def permits_activation_revision(self, activation_revision: int) -> bool:
        """Allow the current revision or the immediately preceding enabled revision."""

        if activation_revision < 0:
            return False
        return (self.available and self.enabled and activation_revision == self.revision) or (
            self.previously_enabled and activation_revision == self.revision - 1
        )


@dataclass(frozen=True, slots=True)
class CostCollectionCursor:
    """Monotonic collection position for one provider scope."""

    package_id: str
    scope_id: str
    revision: int
    resume_token: str | None
    coverage_through_at: datetime
    retention_floor_at: datetime
    analysis_revision: int = 0
    last_published_at: datetime | None = None
    last_published_observation_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("package_id", self.package_id)
        _require_text("scope_id", self.scope_id)
        if self.revision < 0 or self.analysis_revision < 0:
            raise ValueError("cursor revisions MUST be nonnegative")
        _require_aware("coverage_through_at", self.coverage_through_at)
        _require_aware("retention_floor_at", self.retention_floor_at)
        if (self.last_published_at is None) != (self.last_published_observation_id is None):
            raise ValueError("analysis cursor time and observation id MUST be set together")
        if self.last_published_at is not None:
            _require_aware("last_published_at", self.last_published_at)
            _require_text(
                "last_published_observation_id",
                self.last_published_observation_id or "",
            )


@dataclass(frozen=True, slots=True)
class CostObservation:
    """Immutable provider fact with exact time, provenance, and retention."""

    observation_id: str
    package_id: str
    scope_id: str
    service_id: str
    amount: Decimal
    currency: str
    event_start_at: datetime
    event_end_at: datetime
    observed_at: datetime
    recorded_at: datetime
    source_authority: str
    source_uri: str
    completeness: Decimal
    ontology_release_id: str
    ontology_release_digest: str
    evidence_digest: str
    retention_until: datetime

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "package_id",
            "scope_id",
            "service_id",
            "currency",
            "source_authority",
            "source_uri",
            "ontology_release_id",
            "ontology_release_digest",
            "evidence_digest",
        ):
            _require_text(name, str(getattr(self, name)))
        for name in (
            "event_start_at",
            "event_end_at",
            "observed_at",
            "recorded_at",
            "retention_until",
        ):
            _require_aware(name, getattr(self, name))
        if self.amount < 0:
            raise ValueError("cost observation amount MUST be nonnegative")
        if not Decimal("0") <= self.completeness <= Decimal("1"):
            raise ValueError("cost observation completeness MUST be in [0, 1]")
        if self.event_end_at <= self.event_start_at:
            raise ValueError("cost observation event interval MUST be positive")
        if self.observed_at < self.event_end_at or self.recorded_at < self.observed_at:
            raise ValueError("cost observation times MUST be event <= observed <= recorded")
        if self.retention_until <= self.recorded_at:
            raise ValueError("cost observation retention MUST extend beyond recording")


@dataclass(frozen=True, slots=True)
class CostObservationPage:
    """One bounded provider page."""

    observations: tuple[CostObservation, ...]
    next_resume_token: str | None
    complete: bool
    source_authority: str
    bytes_read: int
    collected_at: datetime

    def __post_init__(self) -> None:
        _require_text("source_authority", self.source_authority)
        _require_aware("collected_at", self.collected_at)
        if self.bytes_read < 0:
            raise ValueError("page bytes_read MUST be nonnegative")


@dataclass(frozen=True, slots=True)
class CostCollectionRequest:
    """Bounded provider read request."""

    package_id: str
    scope_id: str
    start_at: datetime
    end_at: datetime
    page_size: int
    deadline_at: datetime

    def __post_init__(self) -> None:
        _require_text("package_id", self.package_id)
        _require_text("scope_id", self.scope_id)
        for name in ("start_at", "end_at", "deadline_at"):
            _require_aware(name, getattr(self, name))
        if self.end_at <= self.start_at or self.deadline_at <= self.end_at:
            raise ValueError("collection time bounds MUST be start < end < deadline")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("collection page_size MUST be in [1, 1000]")


@dataclass(frozen=True, slots=True)
class CostAnalysisSample:
    """Evidence-quality checked sample consumed by an advisory model."""

    scope_id: str
    resource_id: str
    amount_usd: Decimal
    correlation_id: str
    observed_at: datetime
    source_authority: str
    completeness: Decimal
    ontology_release_digest: str

    def __post_init__(self) -> None:
        for name in (
            "scope_id",
            "resource_id",
            "correlation_id",
            "source_authority",
            "ontology_release_digest",
        ):
            _require_text(name, str(getattr(self, name)))
        _require_aware("observed_at", self.observed_at)
        if self.amount_usd < 0:
            raise ValueError("analysis sample amount MUST be nonnegative")
        if not Decimal("0") <= self.completeness <= Decimal("1"):
            raise ValueError("analysis sample completeness MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CostAnomalyAdvisory:
    """Advisory-only anomaly result; it carries no action authority."""

    scope_id: str
    resource_id: str
    amount_usd: Decimal
    baseline_usd: Decimal
    ratio: Decimal
    impact: Decimal
    recommendation: str
    correlation_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("scope_id", "resource_id", "recommendation", "correlation_id"):
            _require_text(name, str(getattr(self, name)))
        _require_aware("observed_at", self.observed_at)
        if min(self.amount_usd, self.baseline_usd, self.ratio, self.impact) < 0:
            raise ValueError("cost anomaly numeric fields MUST be nonnegative")
        if self.impact > 1:
            raise ValueError("cost anomaly impact MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SignedCostEffectEstimate:
    """Signed advisory delta, separate from nonnegative spend-risk estimates."""

    action_type: str
    monthly_delta_usd: Decimal
    confidence: Decimal
    evidence_digest: str
    source_authority: str
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in ("action_type", "evidence_digest", "source_authority"):
            _require_text(name, str(getattr(self, name)))
        for name in ("observed_at", "valid_until"):
            _require_aware(name, getattr(self, name))
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("effect estimate confidence MUST be in [0, 1]")
        if self.valid_until <= self.observed_at:
            raise ValueError("effect estimate validity interval MUST be positive")


class CostPackageActivationReader(Protocol):
    """Read the current authoritative activation revision."""

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None: ...


class CostObservationProvider(Protocol):
    """Collect one bounded page from a read-only CSP adapter."""

    async def collect_cost_page(
        self,
        request: CostCollectionRequest,
        *,
        resume_token: str | None,
    ) -> CostObservationPage: ...


class CostObservationStore(Protocol):
    """Append immutable observations and advance their cursor atomically."""

    async def read_cost_cursor(
        self,
        package_id: str,
        scope_id: str,
    ) -> CostCollectionCursor | None: ...

    async def append_cost_page(
        self,
        page: CostObservationPage,
        *,
        package_id: str,
        scope_id: str,
        expected_revision: int,
        coverage_through_at: datetime,
        retention_floor_at: datetime,
    ) -> bool: ...

    async def read_cost_observations(
        self,
        *,
        package_id: str,
        scope_id: str,
        since: datetime,
        limit: int,
    ) -> tuple[CostObservation, ...]: ...

    async def advance_cost_analysis_cursor(
        self,
        *,
        package_id: str,
        scope_id: str,
        observation_id: str,
        observed_at: datetime,
        expected_analysis_revision: int,
    ) -> bool: ...


class CostAdvisoryProvider(Protocol):
    """Package-owned anomaly and signed-effect calculations."""

    async def analyze_cost_sample(
        self,
        sample: CostAnalysisSample,
    ) -> CostAnomalyAdvisory | None: ...

    def estimate_cost_effect(self, action_type: str) -> SignedCostEffectEstimate | None: ...


class CostSamplePublisher(Protocol):
    """Publish a sample onto typed ingress without calling an agent directly."""

    async def publish_cost_sample(
        self,
        observation: CostObservation,
        *,
        activation_revision: int,
    ) -> None: ...


__all__ = [
    "COST_SAMPLE_EVENT_TYPE",
    "CostAdvisoryProvider",
    "CostAnalysisSample",
    "CostAnomalyAdvisory",
    "CostCollectionCursor",
    "CostCollectionRequest",
    "CostObservation",
    "CostObservationPage",
    "CostObservationProvider",
    "CostObservationStore",
    "CostPackageActivation",
    "CostPackageActivationReader",
    "CostSamplePublisher",
    "SignedCostEffectEstimate",
]
