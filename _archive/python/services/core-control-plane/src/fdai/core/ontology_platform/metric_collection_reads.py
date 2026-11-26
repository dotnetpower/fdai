"""Read one metric window per collection member in bounded batches.

A collection metric read never samples. Members are read in canonical identifier order,
in batches, under one pinned absolute window and a reserved provider-read budget. A
provider failure stops new batches; every member left unread is pending with a typed
reason. A stated comparison or order applies only to members with a complete window, so
a member without one is never filtered in or ranked, and it is listed as unknown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fdai.core.ontology_platform.metric_semantics import (
    MetricSemanticDefinition,
    MetricWindow,
    MetricWindowProvider,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

METRIC_BUDGET_EXHAUSTED = "metric_budget_exhausted"
METRIC_PROVIDER_UNAVAILABLE = "metric_provider_unavailable"
_COMPARATORS = frozenset({"gt", "ge", "lt", "le"})
_DIRECTIONS = frozenset({"ascending", "descending"})


@dataclass(frozen=True, slots=True)
class MemberRead:
    """One member's metric window, or the typed reason it stayed unread."""

    target: OntologyObjectRecord
    definition: MetricSemanticDefinition
    window: MetricWindow | None
    pending_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MetricSelection:
    """The stated comparison or order a collection metric read applies to complete values."""

    comparator: str | None = None
    threshold: Decimal | None = None
    descending: bool | None = None
    limit: int | None = None
    list_unknown: bool = False

    @property
    def selective(self) -> bool:
        return self.comparator is not None or self.descending is not None

    @classmethod
    def from_arguments(
        cls,
        arguments: Mapping[str, Any],
        definitions: Sequence[MetricSemanticDefinition],
    ) -> MetricSelection:
        comparison = {
            key: arguments.get(key) for key in ("comparator", "threshold", "threshold_unit")
        }
        order = {key: arguments.get(key) for key in ("order_direction", "order_limit")}
        list_unknown = arguments.get("list_unknown") is True
        compares = any(value is not None for value in comparison.values())
        orders = any(value is not None for value in order.values())
        if not compares and not orders:
            if list_unknown:
                raise ValueError("listing unknown members needs a comparison or an order")
            return cls()
        if len(definitions) != 1:
            raise ValueError("a metric comparison or order reads exactly one concept")
        selection: dict[str, Any] = {"list_unknown": list_unknown}
        if compares:
            if any(value is None for value in comparison.values()):
                raise ValueError("metric comparison MUST hold comparator, threshold, and unit")
            if comparison["comparator"] not in _COMPARATORS:
                raise ValueError("metric comparator is not reviewed")
            if comparison["threshold_unit"] != definitions[0].canonical_unit:
                raise ValueError("metric comparison unit differs from the canonical unit")
            try:
                threshold = Decimal(str(comparison["threshold"]))
            except InvalidOperation as exc:
                raise ValueError("metric comparison value MUST be a decimal") from exc
            if not threshold.is_finite():
                raise ValueError("metric comparison value MUST be finite")
            selection.update(comparator=comparison["comparator"], threshold=threshold)
        if orders:
            if order["order_direction"] not in _DIRECTIONS:
                raise ValueError("metric order direction is not reviewed")
            limit = order["order_limit"]
            if limit is not None and (
                isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50
            ):
                raise ValueError("metric order limit MUST be a stated count from 1 to 50")
            selection.update(descending=order["order_direction"] == "descending", limit=limit)
        return cls(**selection)

    def matches(self, value: float) -> bool:
        if self.comparator is None or self.threshold is None:
            return True
        measured = Decimal(repr(value))
        return {
            "gt": measured > self.threshold,
            "ge": measured >= self.threshold,
            "lt": measured < self.threshold,
            "le": measured <= self.threshold,
        }[self.comparator]


async def read_members(
    targets: Sequence[OntologyObjectRecord],
    definitions: Sequence[MetricSemanticDefinition],
    *,
    provider: MetricWindowProvider,
    start: datetime,
    end: datetime,
    max_reads: int,
    batch_size: int,
    concurrency: int,
) -> tuple[tuple[MemberRead, ...], str | None]:
    """Read every member and concept pair in order, or mark the rest pending and say why."""

    if max_reads < 1 or batch_size < 1 or concurrency < 1:
        raise ValueError("metric read budget, batch size, and concurrency MUST be positive")
    pairs = [(target, definition) for target in targets for definition in definitions]
    semaphore = asyncio.Semaphore(concurrency)

    async def read(
        target: OntologyObjectRecord, definition: MetricSemanticDefinition
    ) -> MetricWindow:
        async with semaphore:
            result = await provider.read(
                definition=definition,
                resource_id=target.id,
                start=start,
                end=end,
            )
        if (
            result.resource_id != target.id
            or result.concept_id != definition.concept_id
            or result.unit != definition.canonical_unit
            or result.start != start
            or result.end != end
        ):
            raise ValueError("metric provider widened the verified collection request")
        return result

    reads: list[MemberRead] = []
    stop: str | None = None
    for offset in range(0, len(pairs), batch_size):
        batch = pairs[offset : offset + batch_size]
        remaining = max_reads - sum(1 for item in reads if item.window is not None)
        if stop is None and remaining < len(batch):
            # The whole batch must fit the reserved budget before it starts.
            stop = METRIC_BUDGET_EXHAUSTED
        if stop is not None:
            reads.extend(MemberRead(target, definition, None, stop) for target, definition in batch)
            continue
        windows = await asyncio.gather(*(read(target, definition) for target, definition in batch))
        reads.extend(
            MemberRead(target, definition, window)
            for (target, definition), window in zip(batch, windows, strict=True)
        )
        if any(window.missing_reason == "provider_unavailable" for window in windows):
            stop = METRIC_PROVIDER_UNAVAILABLE
    return tuple(reads), stop


__all__ = [
    "METRIC_BUDGET_EXHAUSTED",
    "METRIC_PROVIDER_UNAVAILABLE",
    "MemberRead",
    "MetricSelection",
    "read_members",
]
