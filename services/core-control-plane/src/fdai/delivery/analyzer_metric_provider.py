"""Keep analyzer identities logical while provider metric queries stay exact."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace

from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)


def _identity(value: str) -> str:
    return value


class AnalyzerMetricProvider:
    """Translate only the metric-query resource label at the delivery boundary.

    The wrapped provider receives the target's provider-native reference.
    Returned points are checked against that reference and relabeled with the
    logical Resource id before they re-enter analyzer code.
    """

    def __init__(
        self,
        provider: MetricProvider,
        *,
        targets: Sequence[AnalyzerTarget],
        normalize_provider_ref: Callable[[str], str] = _identity,
    ) -> None:
        self._provider = provider
        self._normalize_provider_ref = normalize_provider_ref
        query_refs: dict[str, str] = {}
        query_ref_owners: dict[str, str] = {}
        for target in targets:
            if target.provider_query_ref is None:
                continue
            query_ref = normalize_provider_ref(target.provider_query_ref.strip()).strip()
            if not query_ref:
                raise ValueError("normalized analyzer provider query reference MUST be non-empty")
            previous = query_refs.get(target.resource_ref)
            if previous is not None and previous != query_ref:
                raise ValueError("analyzer target has conflicting provider query references")
            previous_owner = query_ref_owners.get(query_ref)
            if previous_owner is not None and previous_owner != target.resource_ref:
                raise ValueError(
                    "analyzer provider query reference maps to multiple logical resources"
                )
            query_refs[target.resource_ref] = query_ref
            query_ref_owners[query_ref] = target.resource_ref
        self._query_refs = query_refs

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        logical_ref = query.labels.get("resource_id")
        if logical_ref is None:
            async for point in self._provider.query(query):
                yield point
            return
        provider_ref = self._query_refs.get(logical_ref)
        if provider_ref is None:
            async for point in self._provider.query(query):
                yield point
            return

        labels = dict(query.labels)
        labels["resource_id"] = provider_ref
        provider_query = replace(query, labels=labels)
        async for point in self._provider.query(provider_query):
            point_labels = dict(point.labels)
            returned_ref = point_labels.get("resource_id")
            if (
                returned_ref is not None
                and self._normalize_provider_ref(returned_ref) != provider_ref
            ):
                raise MetricProviderError(
                    "metric provider returned another mapped resource identity"
                )
            if returned_ref is not None:
                point_labels["resource_id"] = logical_ref
            yield replace(point, labels=point_labels)


__all__ = ["AnalyzerMetricProvider"]
