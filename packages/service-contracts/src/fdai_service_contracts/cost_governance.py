"""Versioned, authority-free Cost Governance read contracts."""

from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, TypeVar

from pydantic import Field, model_validator

from fdai_service_contracts.executor_models import ContractBase


class CostGovernanceUnavailableReason(StrEnum):
    """Typed reason that a Cost Governance read cannot proceed."""

    PACKAGE_ABSENT = "package_absent"
    PACKAGE_DISABLED = "package_disabled"
    PACKAGE_INCOMPATIBLE = "package_incompatible"
    HOST_INCOMPATIBLE = "host_incompatible"
    ONTOLOGY_INCOMPATIBLE = "ontology_incompatible"
    MISSING_PROVIDER = "missing_provider"
    ACCESS_GRANT_MISSING = "access_grant_missing"
    ACCESS_GRANT_EXPIRED = "access_grant_expired"
    ACCESS_SCOPE_MISMATCH = "access_scope_mismatch"
    SOURCE_UNAVAILABLE = "source_unavailable"


class CostGranularity(StrEnum):
    """Increasingly detailed row granularity."""

    NONE = "none"
    SUMMARY = "summary"
    GROUP = "group"
    RESOURCE = "resource"


class CostIdentityVisibility(StrEnum):
    """Increasing identity disclosure."""

    NONE = "none"
    PSEUDONYMOUS = "pseudonymous"
    EXACT = "exact"


class CostAmountPrecision(StrEnum):
    """Increasing monetary precision."""

    NONE = "none"
    BAND = "band"
    ROUNDED = "rounded"
    EXACT = "exact"


_GRANULARITY_ORDER = tuple(CostGranularity)
_IDENTITY_ORDER = tuple(CostIdentityVisibility)
_AMOUNT_ORDER = tuple(CostAmountPrecision)
_EnumT = TypeVar("_EnumT", bound=StrEnum)
CostAvailabilityReasonToken = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=(
            r"^(package_absent|host_incompatible|ontology_incompatible|"
            r"missing_provider:[a-z0-9][a-z0-9._:/-]{1,191})$"
        ),
    ),
]


class CostDisclosurePolicy(ContractBase):
    """Server-enforced component-wise Cost Governance disclosure ceiling."""

    granularity: CostGranularity
    identity_visibility: CostIdentityVisibility
    amount_precision: CostAmountPrecision
    small_cell_minimum: Annotated[int, Field(strict=True, ge=1, le=100)] = 3
    rounding_increment: Annotated[Decimal, Field(gt=0)] = Decimal("100")

    def meet(self, other: CostDisclosurePolicy) -> CostDisclosurePolicy:
        """Return a policy no more disclosive than either input."""

        return CostDisclosurePolicy(
            granularity=_minimum(self.granularity, other.granularity, _GRANULARITY_ORDER),
            identity_visibility=_minimum(
                self.identity_visibility,
                other.identity_visibility,
                _IDENTITY_ORDER,
            ),
            amount_precision=_minimum(
                self.amount_precision,
                other.amount_precision,
                _AMOUNT_ORDER,
            ),
            small_cell_minimum=max(self.small_cell_minimum, other.small_cell_minimum),
            rounding_increment=max(self.rounding_increment, other.rounding_increment),
        )


DISCLOSURE_PRESETS: Mapping[str, CostDisclosurePolicy] = {
    "hidden": CostDisclosurePolicy(
        granularity=CostGranularity.NONE,
        identity_visibility=CostIdentityVisibility.NONE,
        amount_precision=CostAmountPrecision.NONE,
    ),
    "aggregate": CostDisclosurePolicy(
        granularity=CostGranularity.GROUP,
        identity_visibility=CostIdentityVisibility.NONE,
        amount_precision=CostAmountPrecision.ROUNDED,
    ),
    "masked": CostDisclosurePolicy(
        granularity=CostGranularity.RESOURCE,
        identity_visibility=CostIdentityVisibility.PSEUDONYMOUS,
        amount_precision=CostAmountPrecision.BAND,
    ),
    "detailed": CostDisclosurePolicy(
        granularity=CostGranularity.RESOURCE,
        identity_visibility=CostIdentityVisibility.EXACT,
        amount_precision=CostAmountPrecision.EXACT,
    ),
}


class CostGovernanceAvailability(ContractBase):
    """Authenticated source and feature-access preflight result."""

    type: Literal["cost-governance.availability"] = "cost-governance.availability"
    schema_version: Literal["1.0.0"] = "1.0.0"
    available: bool
    enabled: bool
    access_allowed: bool
    package_id: str = "fdai-cost-governance"
    activation_revision: Annotated[int | None, Field(ge=0)] = None
    availability_reasons: Annotated[
        tuple[CostAvailabilityReasonToken, ...],
        Field(max_length=32),
    ] = ()
    package_version: Annotated[str | None, Field(max_length=64)] = None
    image_digest: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    asset_manifest_digest: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    semantic_profile_digest: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    ontology_release_digest: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    reason: CostGovernanceUnavailableReason | None = None
    disclosure: CostDisclosurePolicy | None = None

    @model_validator(mode="after")
    def validate_state(self) -> CostGovernanceAvailability:
        if self.available and self.reason is not None:
            raise ValueError("available Cost Governance source cannot have an unavailable reason")
        if self.enabled and not self.available:
            raise ValueError("unavailable Cost Governance source cannot be enabled")
        if len(set(self.availability_reasons)) != len(self.availability_reasons):
            raise ValueError("availability reasons must be unique")
        if self.available == bool(self.availability_reasons):
            raise ValueError("availability must match empty availability reasons")
        if not self.available and self.reason is None:
            raise ValueError("unavailable Cost Governance source requires a typed reason")
        if not self.access_allowed and self.disclosure is not None:
            raise ValueError("denied Cost Governance access cannot disclose a policy")
        attribution = (
            self.package_version,
            self.image_digest,
            self.asset_manifest_digest,
            self.semantic_profile_digest,
            self.ontology_release_digest,
        )
        if self.activation_revision is None:
            if any(value is not None for value in attribution):
                raise ValueError("absent activation cannot carry artifact attribution")
        elif any(value is None for value in attribution):
            raise ValueError("persisted activation requires complete artifact attribution")
        return self


class CostAccessGrant(ContractBase):
    """Revisioned, expiring grant for one user and bounded Cost Governance scope."""

    type: Literal["cost-governance.access-grant"] = "cost-governance.access-grant"
    schema_version: Literal["1.0.0"] = "1.0.0"
    grant_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    revision: Annotated[int, Field(strict=True, ge=0)]
    purpose: Annotated[str, Field(min_length=1, max_length=128)]
    scopes: Annotated[tuple[str, ...], Field(min_length=1, max_length=64)]
    disclosure: CostDisclosurePolicy
    effective_at: datetime
    expires_at: datetime
    source_authority: Annotated[str, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def validate_interval(self) -> CostAccessGrant:
        if self.effective_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Cost Governance grant times must be timezone-aware")
        if self.expires_at <= self.effective_at:
            raise ValueError("Cost Governance grant expiry must follow its effective time")
        if len(set(self.scopes)) != len(self.scopes) or any(
            not item.strip() for item in self.scopes
        ):
            raise ValueError("Cost Governance grant scopes must be unique and non-empty")
        return self


class CostDisclosureCeiling(ContractBase):
    """Revisioned deployment ceiling applied to every Cost Governance grant."""

    type: Literal["cost-governance.disclosure-ceiling"] = "cost-governance.disclosure-ceiling"
    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: Annotated[int, Field(strict=True, ge=0)]
    disclosure: CostDisclosurePolicy
    effective_at: datetime
    source_authority: Annotated[str, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def validate_effective_time(self) -> CostDisclosureCeiling:
        if self.effective_at.tzinfo is None:
            raise ValueError("Cost Governance disclosure ceiling time must be timezone-aware")
        return self


class CostProjectionRecord(ContractBase):
    """Canonical server-side cost fact before disclosure transformation."""

    record_id: Annotated[str, Field(min_length=1, max_length=512)]
    group_id: Annotated[str, Field(min_length=1, max_length=256)]
    resource_id: Annotated[str | None, Field(max_length=2048)] = None
    service_id: Annotated[str, Field(min_length=1, max_length=256)]
    amount: Annotated[Decimal, Field(ge=0)]
    previous_amount: Annotated[Decimal | None, Field(ge=0)] = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    observed_at: datetime
    completeness: Annotated[Decimal, Field(ge=0, le=1)]
    source_authority: Annotated[str, Field(min_length=1, max_length=256)]
    provenance_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    status: Annotated[str | None, Field(max_length=128)] = None


class _CostDetailedProjection(ContractBase):
    """Shared disclosed fact fields for typed Cost Governance projections."""

    record_id: str
    resource: str | None
    service_id: str
    currency: str
    observed_at: datetime
    completeness: Decimal
    source_authority: str
    provenance_digest: str
    status: str | None = None
    amount_band: str | None = None
    amount_rounded: Decimal | None = None
    amount_exact: Decimal | None = None
    relative_change: Decimal | None = None


class CostSummaryProjection(ContractBase):
    """Disclosure-safe grouped or all-scope spend summary."""

    kind: Literal["summary"] = "summary"
    group_id: str | None = None
    currency: str
    record_count: Annotated[int, Field(strict=True, ge=0)]
    suppressed: bool = False
    amount_band: str | None = None
    amount_rounded: Decimal | None = None
    amount_exact: Decimal | None = None


class CostTrendProjection(_CostDetailedProjection):
    """Time-bound trend point derived from one immutable observation."""

    kind: Literal["trend"] = "trend"


class CostResourceEfficiencyProjection(_CostDetailedProjection):
    """Resource-level efficiency projection after server disclosure."""

    kind: Literal["resource"] = "resource"


class CostOptimizationCaseProjection(_CostDetailedProjection):
    """Read-only optimization case projection without execution authority."""

    kind: Literal["optimization_case"] = "optimization_case"


class CostOutcomeProjection(_CostDetailedProjection):
    """Read-only outcome projection without verification or promotion authority."""

    kind: Literal["outcome"] = "outcome"


class CostAnalyticsTrendPoint(ContractBase):
    """One disclosure-safe daily cost point."""

    observed_on: date
    amount: Annotated[Decimal, Field(ge=0)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    completeness: Annotated[Decimal, Field(ge=0, le=1)]


class CostAnalyticsBudget(ContractBase):
    """One pseudonymous effective budget and provider-calculated spend state."""

    budget_ref: Annotated[str, Field(pattern=r"^budget:[0-9a-f]{16}$")]
    amount: Annotated[Decimal, Field(gt=0)]
    current_spend: Annotated[Decimal, Field(ge=0)]
    forecast_spend: Annotated[Decimal | None, Field(ge=0)] = None
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    time_grain: Annotated[str, Field(min_length=1, max_length=32)]


class CostAnalyticsRecommendation(ContractBase):
    """Pseudonymous provider recommendation that remains candidate-only."""

    recommendation_ref: Annotated[str, Field(pattern=r"^recommendation:[0-9a-f]{16}$")]
    resource_ref: Annotated[str | None, Field(pattern=r"^resource:[0-9a-f]{16}$")] = None
    resource_type: Annotated[str, Field(min_length=1, max_length=256)]
    problem: Annotated[str, Field(min_length=1, max_length=512)]
    solution: Annotated[str, Field(min_length=1, max_length=512)]
    impact: Literal["High", "Medium", "Low", "Unknown"]
    monthly_savings: Annotated[Decimal | None, Field(ge=0)] = None
    currency: Annotated[str | None, Field(min_length=3, max_length=3)] = None
    current_sku: Annotated[str | None, Field(max_length=128)] = None
    target_sku: Annotated[str | None, Field(max_length=128)] = None
    utilization_percent: Annotated[Decimal | None, Field(ge=0, le=100)] = None
    utilization_metric: Annotated[str | None, Field(max_length=128)] = None
    observed_at: datetime
    source_authority: Annotated[str, Field(min_length=1, max_length=256)]


class CostAnalyticsProjection(ContractBase):
    """Bounded authoritative analytics that cannot grant action authority."""

    type: Literal["cost-governance.analytics"] = "cost-governance.analytics"
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_authority: Annotated[str, Field(min_length=1, max_length=256)]
    observed_at: datetime
    complete: bool
    trend: Annotated[tuple[CostAnalyticsTrendPoint, ...], Field(max_length=400)] = ()
    budgets: Annotated[tuple[CostAnalyticsBudget, ...], Field(max_length=32)] = ()
    recommendations: Annotated[
        tuple[CostAnalyticsRecommendation, ...],
        Field(max_length=200),
    ] = ()
    limitations: Annotated[tuple[str, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def validate_analytics(self) -> CostAnalyticsProjection:
        if self.observed_at.tzinfo is None:
            raise ValueError("Cost Governance analytics observed_at must be timezone-aware")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("Cost Governance analytics limitations must be unique")
        return self


CostGovernanceItem: TypeAlias = Annotated[
    CostSummaryProjection
    | CostTrendProjection
    | CostResourceEfficiencyProjection
    | CostOptimizationCaseProjection
    | CostOutcomeProjection,
    Field(discriminator="kind"),
]


class CostGovernanceProjection(ContractBase):
    """Versioned server-redacted projection for one Cost Governance workspace tab."""

    type: Literal["cost-governance.projection"] = "cost-governance.projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    surface: Literal["overview", "resource-efficiency", "optimization-cases", "outcomes"]
    disclosure: CostDisclosurePolicy
    generated_at: datetime
    source_authority: str
    complete: bool
    items: tuple[CostGovernanceItem, ...] = ()
    suppressed_count: Annotated[int, Field(strict=True, ge=0)] = 0
    analytics: CostAnalyticsProjection | None = None


def disclose_cost_records(
    records: Sequence[CostProjectionRecord],
    policy: CostDisclosurePolicy,
    *,
    pseudonym_key: bytes | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Transform cost facts before serialization without returning key material."""

    if policy.granularity is CostGranularity.NONE:
        return ()
    if policy.granularity in (CostGranularity.SUMMARY, CostGranularity.GROUP):
        grouped: dict[tuple[str | None, str], list[CostProjectionRecord]] = defaultdict(list)
        for record in records:
            group_id = record.group_id if policy.granularity is CostGranularity.GROUP else None
            grouped[(group_id, record.currency)].append(record)
        return tuple(
            {
                **({"group_id": group_id} if group_id is not None else {}),
                "currency": currency,
                "record_count": len(group),
                **(
                    {"suppressed": True}
                    if len(group) < policy.small_cell_minimum
                    else _amount_projection(sum((item.amount for item in group), Decimal()), policy)
                ),
            }
            for (group_id, currency), group in sorted(grouped.items())
        )
    if policy.identity_visibility is CostIdentityVisibility.PSEUDONYMOUS and not pseudonym_key:
        raise ValueError("masked disclosure requires a server-held pseudonym key")
    return tuple(
        {
            "record_id": record.record_id,
            "resource": _identity(record, policy, pseudonym_key),
            "service_id": record.service_id,
            "currency": record.currency,
            "observed_at": record.observed_at.isoformat(),
            "completeness": str(record.completeness),
            "source_authority": record.source_authority,
            "provenance_digest": record.provenance_digest,
            **({"status": record.status} if record.status is not None else {}),
            **_amount_projection(record.amount, policy, previous=record.previous_amount),
        }
        for record in records
    )


def _minimum(value: _EnumT, other: _EnumT, order: tuple[_EnumT, ...]) -> _EnumT:
    return order[min(order.index(value), order.index(other))]


def _identity(
    record: CostProjectionRecord,
    policy: CostDisclosurePolicy,
    key: bytes | None,
) -> str | None:
    if policy.identity_visibility is CostIdentityVisibility.NONE:
        return None
    raw = record.resource_id or record.record_id
    if policy.identity_visibility is CostIdentityVisibility.EXACT:
        return raw
    assert key is not None
    digest = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:24]
    return f"resource:{digest}"


def _amount_projection(
    amount: Decimal,
    policy: CostDisclosurePolicy,
    *,
    previous: Decimal | None = None,
) -> Mapping[str, object]:
    precision = policy.amount_precision
    if precision is CostAmountPrecision.NONE:
        return {}
    relative = None
    if previous is not None and previous > 0:
        relative = str(((amount - previous) / previous).quantize(Decimal("0.0001")))
    if precision is CostAmountPrecision.BAND:
        exponent = max(0, len(str(int(amount))) - 1)
        lower = Decimal(10) ** exponent if amount else Decimal()
        return {
            "amount_band": "0" if not amount else f"{lower}+",
            **({"relative_change": relative} if relative is not None else {}),
        }
    if precision is CostAmountPrecision.ROUNDED:
        rounded = (amount / policy.rounding_increment).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        ) * policy.rounding_increment
        return {"amount_rounded": str(rounded)}
    return {
        "amount_exact": str(amount),
        **({"relative_change": relative} if relative is not None else {}),
    }


__all__ = [
    "CostAccessGrant",
    "CostAmountPrecision",
    "CostDisclosurePolicy",
    "CostDisclosureCeiling",
    "CostGovernanceAvailability",
    "CostGovernanceItem",
    "CostGovernanceProjection",
    "CostGovernanceUnavailableReason",
    "CostGranularity",
    "CostIdentityVisibility",
    "CostProjectionRecord",
    "CostOptimizationCaseProjection",
    "CostOutcomeProjection",
    "CostResourceEfficiencyProjection",
    "CostSummaryProjection",
    "CostTrendProjection",
    "DISCLOSURE_PRESETS",
    "disclose_cost_records",
]
