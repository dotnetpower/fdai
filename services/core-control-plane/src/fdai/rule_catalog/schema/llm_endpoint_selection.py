"""Catalog, quota, and deployment projection for LLM endpoint pools."""

from __future__ import annotations

from typing import Any

from fdai.rule_catalog.schema.llm_registry import LlmRegistry


def _available_capacity_tpm(
    quota: Any,
    *,
    region: str,
    publisher: str,
    family: str,
    sku: str,
) -> int:
    sku_query = getattr(quota, "available_capacity_tpm_for_sku", None)
    if callable(sku_query):
        return int(
            sku_query(
                region=region,
                publisher=publisher,
                family=family,
                sku=sku,
            )
        )
    if sku != "Standard":
        return 0
    return int(
        quota.available_capacity_tpm(
            region=region,
            publisher=publisher,
            family=family,
        )
    )


def _stable_version(model_versions: Any, *, region: str, publisher: str, family: str) -> str | None:
    if model_versions is None:
        return None
    version = model_versions.latest_stable_version(
        region=region,
        publisher=publisher,
        family=family,
    )
    if version is None:
        raise ValueError(f"no stable model version for synthesized deployment {publisher}/{family}")
    if not isinstance(version, str):
        raise ValueError("model version query MUST return a string or None")
    return version


def narrator_deployment_name(family: str) -> str:
    """Return the URL-safe Azure deployment name for a narrator family."""
    return "narrator-" + family.replace(".", "-")


def reasoner_primary_deployment_name(family: str) -> str:
    """Return the URL-safe Azure deployment name for a T2 primary family."""
    return "t2primary-" + family.replace(".", "-")


def web_search_deployment_name(family: str) -> str:
    """Return the URL-safe Azure deployment name for a web-search family."""
    return "websearch-" + family.replace(".", "-")


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
        available = _available_capacity_tpm(
            quota,
            region=region,
            publisher=pref.publisher,
            family=pref.family,
            sku=spec.sku.value,
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
    model_versions: Any = None,
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
        available = _available_capacity_tpm(
            quota,
            region=region,
            publisher=pref.publisher,
            family=pref.family,
            sku=spec.sku.value,
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
                version=_stable_version(
                    model_versions,
                    region=region,
                    publisher=pref.publisher,
                    family=pref.family,
                ),
                reasons=(f"narrator_deployment_for={capability_name}",),
            )
        )
    return tuple(out)


def collect_vision_candidates(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    endpoint: str,
    narrator_candidates: tuple[Any, ...],
    api_version: str = "2024-08-01-preview",
    capability_name: str = "t1.vision",
) -> tuple[Any, ...]:
    """Collect vision-capable candidates backed by narrator deployments.

    The capability resolves independently, but only families already emitted
    in ``narrator_candidates`` are eligible. This keeps image routing explicit
    without provisioning duplicate Azure deployments or consuming quota twice.
    """
    from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate

    deployed = {candidate.deployment for candidate in narrator_candidates}
    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    return tuple(
        NarratorCandidate(
            endpoint=endpoint,
            deployment=deployment,
            api_version=api_version,
        )
        for pref in prefs
        if (deployment := narrator_deployment_name(pref.family)) in deployed
    )


def collect_web_search_candidates(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    endpoint: str,
    api_version: str = "2024-08-01-preview",
    capability_name: str = "t1.web_search",
) -> tuple[Any, ...]:
    """Collect model candidates dedicated to the Responses web-search tool."""
    from fdai.rule_catalog.schema.llm_resolver import NarratorCandidate

    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    return tuple(
        NarratorCandidate(
            endpoint=endpoint,
            deployment=web_search_deployment_name(pref.family),
            api_version=api_version,
        )
        for pref in prefs
    )


def collect_web_search_deployments(
    *,
    registry: LlmRegistry,
    region: str,
    catalog: Any,
    quota: Any,
    model_versions: Any = None,
    capability_name: str = "t1.web_search",
) -> tuple[Any, ...]:
    """Emit one provisionable capability for each web-search candidate."""
    from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus, ResolvedCapability

    prefs = _viable_narrator_prefs(
        registry=registry,
        region=region,
        catalog=catalog,
        quota=quota,
        capability_name=capability_name,
    )
    spec = registry.models.get(capability_name)
    if spec is None:
        return ()
    return tuple(
        ResolvedCapability(
            name=web_search_deployment_name(pref.family),
            status=CapabilityStatus.RESOLVED,
            publisher=pref.publisher,
            family=pref.family,
            sku=spec.sku.value,
            capacity_tpm=min(
                spec.requested_capacity,
                _available_capacity_tpm(
                    quota,
                    region=region,
                    publisher=pref.publisher,
                    family=pref.family,
                    sku=spec.sku.value,
                ),
            ),
            invocation=spec.invocation.value,
            version=_stable_version(
                model_versions,
                region=region,
                publisher=pref.publisher,
                family=pref.family,
            ),
            reasons=(f"web_search_deployment_for={capability_name}",),
        )
        for pref in prefs
    )


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
    model_versions: Any = None,
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
        available = _available_capacity_tpm(
            quota,
            region=region,
            publisher=pref.publisher,
            family=pref.family,
            sku=spec.sku.value,
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
                version=_stable_version(
                    model_versions,
                    region=region,
                    publisher=pref.publisher,
                    family=pref.family,
                ),
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
    "collect_vision_candidates",
    "collect_primary_candidates",
    "collect_primary_deployments",
    "narrator_deployment_name",
    "reasoner_primary_deployment_name",
]
