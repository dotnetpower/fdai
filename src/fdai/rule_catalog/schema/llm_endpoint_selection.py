"""Catalog, quota, and deployment projection for LLM endpoint pools."""

from __future__ import annotations

from typing import Any

from fdai.rule_catalog.schema.llm_registry import LlmRegistry


def narrator_deployment_name(family: str) -> str:
    """Return the URL-safe Azure deployment name for a narrator family."""
    return "narrator-" + family.replace(".", "-")


def reasoner_primary_deployment_name(family: str) -> str:
    """Return the URL-safe Azure deployment name for a T2 primary family."""
    return "t2primary-" + family.replace(".", "-")


def _viable_narrator_prefs(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    capability_name: str,
) -> list[Any]:
    spec = registry.models.get(capability_name)
    if spec is None:
        return []
    catalog_families = catalog.families_in_region(region)
    seen: set[str] = set()
    out: list[Any] = []
    for pref in spec.preferences:
        if pref.family in seen or pref.family not in catalog_families:
            continue
        available = quota.available_capacity_tpm(
            region=region, publisher=pref.publisher, family=pref.family
        )
        if available <= 0:
            continue
        seen.add(pref.family)
        out.append(pref)
    return out


def collect_narrator(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    endpoint: str,
    api_version: str = "2024-08-01-preview",
    capability_name: str = "t1.judge",
) -> tuple[Any | None, tuple[Any, ...]]:
    from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate

    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    if not prefs:
        return None, ()
    candidates = tuple(
        NarratorCandidate(
            endpoint=endpoint,
            deployment=narrator_deployment_name(pref.family),
            api_version=api_version,
        )
        for pref in prefs
    )
    return candidates[0], candidates


def collect_narrator_deployments(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    capability_name: str = "t1.judge",
) -> tuple[Any, ...]:
    from fdai.rule_catalog.schema.llm_resolver import (
        CapabilityStatus,
        ResolvedCapability,
        ResolverError,
    )

    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    spec = registry.models.get(capability_name)
    if spec is None or not prefs:
        return ()
    out: list[Any] = []
    seen_names: dict[str, str] = {}
    for pref in prefs:
        deployment_name = narrator_deployment_name(pref.family)
        if deployment_name in seen_names:
            raise ResolverError(
                f"narrator_deployment_name collision: family {pref.family!r} "
                f"and {seen_names[deployment_name]!r} both normalise to "
                f"{deployment_name!r}. Adjust llm-registry.yaml preferences."
            )
        seen_names[deployment_name] = pref.family
        available = quota.available_capacity_tpm(
            region=region, publisher=pref.publisher, family=pref.family
        )
        effective = min(spec.requested_capacity, available)
        out.append(
            ResolvedCapability(
                name=deployment_name,
                status=CapabilityStatus.RESOLVED,
                publisher=pref.publisher,
                family=pref.family,
                sku=spec.sku.value,
                capacity_tpm=effective,
                invocation=spec.invocation.value,
                reasons=(f"narrator_deployment_for={capability_name}",),
            )
        )
    return tuple(out)


def collect_primary_candidates(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    endpoint: str,
    api_version: str = "2024-06-01",
    capability_name: str = "t2.reasoner.primary",
) -> tuple[Any | None, tuple[Any, ...]]:
    from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate

    prefs = _viable_primary_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    if not prefs:
        return None, ()
    candidates = tuple(
        NarratorCandidate(
            endpoint=endpoint,
            deployment=reasoner_primary_deployment_name(pref.family),
            api_version=api_version,
        )
        for pref in prefs
    )
    return candidates[0], candidates


def collect_primary_deployments(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    capability_name: str = "t2.reasoner.primary",
) -> tuple[Any, ...]:
    from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedCapability

    prefs = _viable_primary_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    spec = registry.models.get(capability_name)
    if spec is None or not prefs:
        return ()
    out: list[Any] = []
    for pref in prefs:
        available = quota.available_capacity_tpm(
            region=region, publisher=pref.publisher, family=pref.family
        )
        effective = min(spec.requested_capacity, available)
        out.append(
            ResolvedCapability(
                name=reasoner_primary_deployment_name(pref.family),
                status=CapabilityStatus.RESOLVED,
                publisher=pref.publisher,
                family=pref.family,
                sku=spec.sku.value,
                capacity_tpm=effective,
                invocation=spec.invocation.value,
                reasons=(f"primary_pool_deployment_for={capability_name}",),
            )
        )
    return tuple(out)


def _viable_primary_prefs(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    capability_name: str,
) -> list[Any]:
    from fdai.rule_catalog.schema.llm_resolver import ResolverError

    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    publishers = {pref.publisher for pref in prefs}
    if len(publishers) > 1:
        raise ResolverError(
            "t2_primary_pool_cross_publisher: "
            f"{capability_name} viable candidates span publishers "
            f"{sorted(publishers)!r}. A latency-routed primary pool MUST be "
            "single-publisher so the mixed-model invariant "
            "(primary.publisher != secondary.publisher) still holds. Adjust "
            "llm-registry.yaml so this capability's preferences share one "
            "publisher, or leave the pool single-entry."
        )
    return prefs


__all__ = [
    "collect_narrator",
    "collect_narrator_deployments",
    "collect_primary_candidates",
    "collect_primary_deployments",
    "narrator_deployment_name",
    "reasoner_primary_deployment_name",
]
