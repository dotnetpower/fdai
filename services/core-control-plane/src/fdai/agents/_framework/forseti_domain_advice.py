"""Resource-keyed domain advice intake for Forseti arbitration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from fdai.agents._framework import forseti_durability as _durability
from fdai.agents._framework.forseti_decision_helpers import (
    is_conflict,
    signal_impact,
    source_freshness,
)
from fdai.core.operational_context import SourceFreshness


async def ingest_domain_signal(
    host: Any,
    domain: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Accumulate one domain recommendation without mixing observation cutoffs."""

    resource_id = str(payload.get("resource_id") or payload.get("scope") or "")
    recommendation = str(payload.get("recommendation", ""))
    if not resource_id or not recommendation:
        return None
    observed_at = str(payload.get("observed_at") or "")
    correlation_id = str(payload.get("correlation_id") or "")
    freshness = source_freshness(payload.get("source_freshness"))
    revision_window_seconds = _revision_window_seconds(freshness)
    existing_correlation_values = set(
        (host._domain_correlation_ids.get(resource_id) or {}).values()
    )
    if not correlation_id and len(existing_correlation_values) == 1:
        correlation_id = next(iter(existing_correlation_values))
    observed_by_domain = host._domain_observed_at.get(resource_id)
    if observed_by_domain is None:
        observed_by_domain = {}
        host._domain_observed_at.set(resource_id, observed_by_domain)
    if observed_at and observed_by_domain:
        same_replay = bool(correlation_id and correlation_id in existing_correlation_values)
        existing_cutoffs = tuple(
            _domain_cutoff(value) for value in observed_by_domain.values() if value
        )
        incoming_cutoff = _domain_cutoff(observed_at)
        if (
            not same_replay
            and incoming_cutoff is not None
            and any(
                existing is not None
                and incoming_cutoff < existing
                and (existing - incoming_cutoff).total_seconds() >= revision_window_seconds
                for existing in existing_cutoffs
            )
        ):
            host.record_behavior("domain_advice:stale")
            await _durability.persist_domain_advice(host, resource_id)
            return None
        if (
            not same_replay
            and incoming_cutoff is not None
            and any(
                existing is not None
                and incoming_cutoff > existing
                and (incoming_cutoff - existing).total_seconds() > revision_window_seconds
                for existing in existing_cutoffs
            )
        ):
            _clear_resource_advice(host, resource_id)
            observed_by_domain = {}
            host._domain_observed_at.set(resource_id, observed_by_domain)
            host.record_behavior("domain_advice:superseded")
    advice = host._domain_advice.get(resource_id)
    if advice is None:
        advice = {}
        host._domain_advice.set(resource_id, advice)
    advice[domain] = recommendation
    impacts = host._domain_impact.get(resource_id)
    if impacts is None:
        impacts = {}
        host._domain_impact.set(resource_id, impacts)
    impacts[domain] = signal_impact(domain, payload)
    raw_arguments = payload.get("action_arguments")
    if isinstance(raw_arguments, Mapping):
        arguments = host._domain_arguments.get(resource_id)
        if arguments is None:
            arguments = {}
            host._domain_arguments.set(resource_id, arguments)
        arguments[domain] = {
            str(name): value for name, value in raw_arguments.items() if isinstance(name, str)
        }
    if observed_at:
        observed_by_domain[domain] = observed_at
    if correlation_id:
        correlations = host._domain_correlation_ids.get(resource_id)
        if correlations is None:
            correlations = {}
            host._domain_correlation_ids.set(resource_id, correlations)
        correlations[domain] = correlation_id
    if freshness:
        freshness_by_domain = host._domain_source_freshness.get(resource_id)
        if freshness_by_domain is None:
            freshness_by_domain = {}
            host._domain_source_freshness.set(resource_id, freshness_by_domain)
        freshness_by_domain[domain] = freshness
    if not is_conflict(advice):
        await _durability.persist_domain_advice(host, resource_id)
        return None
    if not correlation_id:
        host.record_behavior("arbitration_invalid_identity")
        raise ValueError("arbitration input correlation_id MUST be non-empty")
    request = await host._emit_arbitration_request(
        resource_id=resource_id,
        advice=dict(advice),
        correlation_id=correlation_id,
        impacts=dict(impacts),
        arguments_by_domain=dict(host._domain_arguments.get(resource_id) or {}),
        observed_at=_shared_domain_observed_at(observed_by_domain),
        domain_observed_at=dict(observed_by_domain),
        domain_correlation_ids=dict(host._domain_correlation_ids.get(resource_id) or {}),
        domain_source_freshness=dict(host._domain_source_freshness.get(resource_id) or {}),
        source_freshness=_merged_domain_freshness(
            host._domain_source_freshness.get(resource_id) or {}
        ),
    )
    _clear_resource_advice(host, resource_id)
    await _durability.persist_domain_advice(host, resource_id, status="consumed")
    return cast(dict[str, Any], request)


def _clear_resource_advice(host: Any, resource_id: str) -> None:
    host._domain_advice.pop(resource_id, None)
    host._domain_impact.pop(resource_id, None)
    host._domain_observed_at.pop(resource_id, None)
    host._domain_arguments.pop(resource_id, None)
    host._domain_correlation_ids.pop(resource_id, None)
    host._domain_source_freshness.pop(resource_id, None)


def _domain_cutoff(value: str) -> datetime | None:
    try:
        cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if cutoff.tzinfo is None:
        return None
    return cutoff


def _shared_domain_observed_at(observed_by_domain: Mapping[str, str]) -> str:
    values = {value for value in observed_by_domain.values() if value}
    if len(values) == 1:
        return next(iter(values))
    return ""


def _merged_domain_freshness(
    freshness_by_domain: Mapping[str, tuple[SourceFreshness, ...]],
) -> tuple[SourceFreshness, ...]:
    merged: list[SourceFreshness] = []
    seen: set[tuple[str, str, int]] = set()
    for values in freshness_by_domain.values():
        for item in values:
            key = (item.source, item.observed_at.isoformat(), item.max_age_seconds)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return tuple(merged)


def _revision_window_seconds(freshness: tuple[SourceFreshness, ...]) -> int:
    if not freshness:
        return 3600
    return min(item.max_age_seconds for item in freshness)


__all__ = ["ingest_domain_signal"]
