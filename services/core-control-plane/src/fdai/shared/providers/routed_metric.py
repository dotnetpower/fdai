"""Routed / composite metric provider - per-metric dispatch across backends.

Design contract: the top-level A + C combo from the real-time detection
review. The Kafka event path is already sub-second real-time; sampled
metrics need a periodic tick + a fast telemetry backend. Prometheus
(AKS Managed Prometheus, 15 s scrape) is the fast primary for AKS-scoped
metrics; Azure Monitor Logs (KQL) is the slower fallback for
non-AKS Azure resources (App Gateway, MySQL, Azure OpenAI, APIM).

Instead of a stateful "try primary, catch, try fallback" chain -
which can double-yield partial samples across providers and hide
real failures behind the fallback - this class dispatches on
``metric_name`` deterministically: each provider ships with an
explicit set of metric names it supports; the query goes to the
first provider whose set includes it. A metric absent from every
route raises :class:`MetricProviderError` fail-closed.

CSP-neutral: it imports only the metric Protocol and the stdlib, so
it stays under the ``core/``-adjacent portability contract even
though it lives under ``shared/providers/`` (matching
:class:`StaticMetricProvider`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)


@dataclass(frozen=True, slots=True)
class MetricRoute:
    """One (provider, supported_metrics) tier in a routing table.

    ``supported_metrics`` is the exact set of ``MetricQuery.metric_name``
    values the provider is authorized to handle. Explicit so the caller
    sees the routing table at composition time - a silent overlap between
    tiers is a defect (the earlier tier always wins deterministically).
    """

    provider: MetricProvider
    supported_metrics: frozenset[str]

    def __post_init__(self) -> None:
        if not self.supported_metrics:
            raise ValueError(
                "MetricRoute.supported_metrics MUST be non-empty - an empty "
                "route can never serve a query and is a wiring bug"
            )


class RoutedMetricProvider:
    """Composite :class:`MetricProvider` that dispatches on ``metric_name``.

    ``routes`` is ordered: for a given query, the first route whose
    ``supported_metrics`` contains ``query.metric_name`` handles it. An
    overlap between routes is allowed (the first wins), which is how the
    "Prom primary + AML fallback" pattern falls out: Prom declares the
    AKS-scoped metrics it can serve, AML declares the full 14-metric
    catalog; Prom wins for its subset.
    """

    def __init__(self, routes: Iterable[MetricRoute]) -> None:
        route_tuple = tuple(routes)
        if not route_tuple:
            raise ValueError(
                "RoutedMetricProvider requires >= 1 route - an empty "
                "routing table fails every query and is never useful"
            )
        self._routes: tuple[MetricRoute, ...] = route_tuple

    async def query(self, query: MetricQuery) -> AsyncIterator[MetricPoint]:
        for route in self._routes:
            if query.metric_name in route.supported_metrics:
                async for point in route.provider.query(query):
                    yield point
                return
        raise MetricProviderError(
            f"no route serves metric {query.metric_name!r} "
            f"(available across routes: {sorted(self.routed_metrics())})"
        )

    def routed_metrics(self) -> frozenset[str]:
        """Return the union of every route's supported metrics.

        Useful for start-up logging and for a coverage test that asserts
        the routing table together covers every analyzer-referenced
        metric.
        """
        merged: set[str] = set()
        for route in self._routes:
            merged.update(route.supported_metrics)
        return frozenset(merged)

    def route_for(self, metric_name: str) -> str | None:
        """Return the type-name of the provider that would handle
        ``metric_name``, or ``None`` when no route matches.

        Diagnostic only - used by ``analyzer_tick_cli`` startup logging
        so an operator can see at a glance which backend serves which
        metric without running an actual query.
        """
        for route in self._routes:
            if metric_name in route.supported_metrics:
                return type(route.provider).__name__
        return None


def route_summary(provider: MetricProvider) -> Mapping[str, str] | None:
    """Return a ``metric_name -> provider_type`` map for a routed provider.

    Returns ``None`` when ``provider`` is not a :class:`RoutedMetricProvider`
    (nothing interesting to summarize for a single-backend adapter). Kept
    outside the class so a caller can call it defensively without an
    ``isinstance`` guard at every call site.
    """
    if not isinstance(provider, RoutedMetricProvider):
        return None
    return {name: provider.route_for(name) or "?" for name in provider.routed_metrics()}


__all__ = [
    "MetricRoute",
    "RoutedMetricProvider",
    "route_summary",
]
