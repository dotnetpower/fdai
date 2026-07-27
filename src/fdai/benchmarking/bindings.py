"""Immutable provider bundle supplied by an installed benchmark plugin."""

from __future__ import annotations

from dataclasses import dataclass, replace

from fdai.benchmarking.adapter import BenchmarkAdapter
from fdai.composition import Container
from fdai.shared.providers.inventory import Inventory
from fdai.shared.providers.log_query import LogQueryProvider
from fdai.shared.providers.metric import MetricProvider
from fdai.shared.providers.trace_query import TraceQueryProvider


@dataclass(frozen=True, slots=True)
class BenchmarkBindings:
    """External harness plus optional read-only FDAI provider overrides."""

    adapter: BenchmarkAdapter
    metric_provider: MetricProvider | None = None
    log_query_provider: LogQueryProvider | None = None
    trace_query_provider: TraceQueryProvider | None = None
    inventory: Inventory | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, BenchmarkAdapter):
            raise TypeError("adapter MUST implement BenchmarkAdapter")
        if not self.adapter.adapter_id.strip():
            raise ValueError("adapter_id MUST be non-empty")


def bind_benchmark_providers(container: Container, bindings: BenchmarkBindings) -> Container:
    """Return a container with only the plugin's declared read seams replaced."""

    return replace(
        container,
        metric_provider=(
            bindings.metric_provider
            if bindings.metric_provider is not None
            else container.metric_provider
        ),
        log_query_provider=(
            bindings.log_query_provider
            if bindings.log_query_provider is not None
            else container.log_query_provider
        ),
        trace_query_provider=(
            bindings.trace_query_provider
            if bindings.trace_query_provider is not None
            else container.trace_query_provider
        ),
        inventory=bindings.inventory if bindings.inventory is not None else container.inventory,
    )


__all__ = ["BenchmarkBindings", "bind_benchmark_providers"]
