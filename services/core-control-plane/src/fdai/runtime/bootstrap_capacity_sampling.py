"""Bind reviewed read-only capacity sampling only to explicit current inventory targets."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.agents import MAX_RECURRING_SAMPLES
from fdai.composition import Container
from fdai.core.operational_evidence.registry_json import load_strict_json_text
from fdai.delivery.analyzer_inventory import build_analyzer_inventory_sources
from fdai.delivery.capacity_metric_sampler import CapacityMetricSampler
from fdai.delivery.repo_assets import repo_asset_root
from fdai.runtime.metric_semantic_catalog import load_metric_semantic_registry
from fdai.shared.providers.metric import NoopMetricProvider


def build_capacity_sampler(
    *,
    container: Container,
    environment: Mapping[str, str],
) -> CapacityMetricSampler | None:
    """An absent target declaration is unavailable, never a fabricated capacity population."""
    raw = environment.get("FDAI_FREYR_TARGETS_JSON", "").strip()
    if not raw or isinstance(container.metric_provider, NoopMetricProvider):
        return None
    parsed = load_strict_json_text(raw, label="Freyr capacity targets")
    if not isinstance(parsed, Mapping) or not 1 <= len(parsed) <= MAX_RECURRING_SAMPLES:
        raise ValueError("Freyr targets MUST be a bounded logical-id to canonical-type mapping")
    targets: dict[str, str] = {}
    for resource_id, resource_type in parsed.items():
        if (
            not isinstance(resource_id, str)
            or not resource_id.strip()
            or len(resource_id) > 512
            or not isinstance(resource_type, str)
            or not resource_type.strip()
            or len(resource_type) > 128
            or resource_id != resource_id.strip()
            or resource_type != resource_type.strip()
        ):
            raise ValueError("Freyr target identity or type is invalid")
        targets[resource_id] = resource_type
    inventory = build_analyzer_inventory_sources(environment.get("FDAI_STATE_STORE_DSN", ""))
    if inventory is None:
        return None
    registry = load_metric_semantic_registry(
        repo_asset_root() / "rule-catalog" / "vocabulary" / "metric-semantics.yaml"
    )
    return CapacityMetricSampler(
        provider=container.metric_provider,
        inventory=inventory.provider_references,
        registry=registry,
        targets=targets,
    )
