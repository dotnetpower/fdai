"""Build and reconcile governed Azure discovery coverage receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryCoverageStatus,
    DiscoveryProfile,
    DiscoveryQueryPlan,
    DiscoveryScopeKind,
    DiscoveryUniverse,
)
from fdai_service_contracts.discovery_evidence import (
    DiscoveryCoverageReceipt,
    ProviderExecutionReceipt,
    discovery_coverage_receipt_digest,
)
from fdai_service_contracts.ontology_query import content_digest


@dataclass(frozen=True, slots=True)
class DiscoveryCoverageClaim:
    """One configured universe/backend claim requiring independent live evidence."""

    provider_type: str
    universe: DiscoveryUniverse
    scope_kind: DiscoveryScopeKind
    backend: DiscoveryBackend
    profile_revision: str


@dataclass(frozen=True, slots=True)
class DiscoveryCoverageGap:
    """One uncovered claim with a stable reason code and no provider error text."""

    claim: DiscoveryCoverageClaim
    reason_code: str


@dataclass(frozen=True, slots=True)
class DiscoveryCoverageReconciliation:
    """Replay-stable reconciliation outcome that grants no runtime authority."""

    claims: tuple[DiscoveryCoverageClaim, ...]
    matched_receipt_digests: tuple[str, ...]
    gaps: tuple[DiscoveryCoverageGap, ...]
    complete: bool
    reconciliation_digest: str
    execution_authority: bool = False


def build_discovery_coverage_receipt(
    *,
    profile: DiscoveryProfile,
    plan: DiscoveryQueryPlan,
    execution_receipt: ProviderExecutionReceipt,
    observed_provider_types: tuple[str, ...],
    discovered_count: int,
    platform_version: str,
    source: str,
    observed_at: datetime,
    state: DiscoveryCoverageStatus = DiscoveryCoverageStatus.COVERED,
) -> DiscoveryCoverageReceipt:
    """Bind one exact plan and executed read receipt into a coverage proof."""

    if plan.profile_id != profile.profile_id or plan.profile_revision != profile.revision:
        raise ValueError("coverage plan MUST match the discovery profile revision")
    if len(plan.universes) != 1:
        raise ValueError("coverage receipt requires one plan universe")
    if state not in {DiscoveryCoverageStatus.COVERED, DiscoveryCoverageStatus.FALLBACK}:
        raise ValueError("successful coverage construction requires a complete state")
    if len(observed_provider_types) != len(set(observed_provider_types)):
        raise ValueError("observed provider types MUST be unique")
    values: dict[str, object] = {
        "cloud": profile.cloud,
        "provider_type": profile.provider_type,
        "universe": plan.universes[0],
        "scope_kind": plan.scope_kind,
        "backend": plan.backend,
        "profile_revision": profile.revision,
        "platform_version": platform_version,
        "state": state,
        "scope_digest": plan.scope_digest,
        "plan_digest": plan.plan_digest,
        "execution_receipt_digest": execution_receipt.receipt_digest,
        "observed_provider_types": tuple(sorted(observed_provider_types, key=str.casefold)),
        "discovered_count": discovered_count,
        "complete": True,
        "truncated": False,
        "source": source,
        "observed_at": observed_at,
        "execution_authority": False,
    }
    return DiscoveryCoverageReceipt.model_validate(
        {"receipt_digest": discovery_coverage_receipt_digest(**values), **values}
    )


def discovery_coverage_claims(
    profiles: tuple[DiscoveryProfile, ...],
    *,
    backend: DiscoveryBackend = DiscoveryBackend.RESOURCE_GRAPH,
    scope_kind: DiscoveryScopeKind = DiscoveryScopeKind.SUBSCRIPTION,
) -> tuple[DiscoveryCoverageClaim, ...]:
    """Derive finite claims only for profiles registering the requested backend and scope."""

    claims: list[DiscoveryCoverageClaim] = []
    for profile in profiles:
        universes = {
            universe
            for operation in profile.operations
            if operation.backend is backend and scope_kind in operation.scope_kinds
            for universe in operation.universes
        }
        claims.extend(
            DiscoveryCoverageClaim(
                provider_type=profile.provider_type,
                universe=universe,
                scope_kind=scope_kind,
                backend=backend,
                profile_revision=profile.revision,
            )
            for universe in sorted(universes, key=lambda item: item.value)
        )
    return tuple(
        sorted(
            claims,
            key=lambda item: (
                item.provider_type.casefold(),
                item.universe.value,
                item.scope_kind.value,
                item.backend.value,
            ),
        )
    )


def reconcile_discovery_coverage(
    *,
    claims: tuple[DiscoveryCoverageClaim, ...],
    receipts: tuple[DiscoveryCoverageReceipt, ...],
    evaluated_at: datetime,
    max_age_seconds: int,
    require_live: bool = True,
) -> DiscoveryCoverageReconciliation:
    """Require one fresh complete receipt per claim without mutating any catalog state."""

    if evaluated_at.tzinfo is None:
        raise ValueError("coverage reconciliation evaluated_at MUST include a timezone")
    if max_age_seconds < 1:
        raise ValueError("coverage reconciliation max_age_seconds MUST be positive")
    matched: list[str] = []
    gaps: list[DiscoveryCoverageGap] = []
    for claim in claims:
        candidates = tuple(receipt for receipt in receipts if _matches(claim, receipt))
        if not candidates:
            gaps.append(DiscoveryCoverageGap(claim=claim, reason_code="receipt_missing"))
            continue
        fresh = tuple(
            receipt
            for receipt in candidates
            if 0 <= (evaluated_at - receipt.observed_at).total_seconds() <= max_age_seconds
        )
        if not fresh:
            gaps.append(DiscoveryCoverageGap(claim=claim, reason_code="receipt_stale"))
            continue
        live = tuple(
            receipt for receipt in fresh if not require_live or receipt.source == "live_canary"
        )
        if not live:
            gaps.append(DiscoveryCoverageGap(claim=claim, reason_code="live_receipt_missing"))
            continue
        selected = max(live, key=lambda receipt: (receipt.observed_at, receipt.receipt_digest))
        matched.append(selected.receipt_digest)
    complete = not gaps and len(matched) == len(claims)
    body = {
        "claims": [
            {
                "provider_type": claim.provider_type,
                "universe": claim.universe.value,
                "scope_kind": claim.scope_kind.value,
                "backend": claim.backend.value,
                "profile_revision": claim.profile_revision,
            }
            for claim in claims
        ],
        "matched_receipt_digests": tuple(sorted(matched)),
        "gaps": [
            {
                "provider_type": gap.claim.provider_type,
                "universe": gap.claim.universe.value,
                "reason_code": gap.reason_code,
            }
            for gap in gaps
        ],
        "complete": complete,
        "execution_authority": False,
    }
    return DiscoveryCoverageReconciliation(
        claims=claims,
        matched_receipt_digests=tuple(sorted(matched)),
        gaps=tuple(gaps),
        complete=complete,
        reconciliation_digest=content_digest(body),
    )


def _matches(claim: DiscoveryCoverageClaim, receipt: DiscoveryCoverageReceipt) -> bool:
    return (
        receipt.provider_type.casefold() == claim.provider_type.casefold()
        and receipt.universe is claim.universe
        and receipt.scope_kind is claim.scope_kind
        and receipt.backend is claim.backend
        and receipt.profile_revision == claim.profile_revision
        and receipt.complete
        and not receipt.truncated
        and receipt.state in {DiscoveryCoverageStatus.COVERED, DiscoveryCoverageStatus.FALLBACK}
    )


__all__ = [
    "DiscoveryCoverageClaim",
    "DiscoveryCoverageGap",
    "DiscoveryCoverageReconciliation",
    "build_discovery_coverage_receipt",
    "discovery_coverage_claims",
    "reconcile_discovery_coverage",
]
