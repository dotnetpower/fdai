"""Typed recipe tool used by verified adaptive telemetry query nodes."""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from .telemetry_evidence import (
    TelemetryEvidenceNeed,
    TelemetryEvidenceProvider,
    TelemetryEvidenceReceipt,
)
from .telemetry_recipes import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ReviewedTelemetryRecipeCatalog,
)

_MAX_RETAINED_RECEIPTS = 10_000


class TelemetryEvidenceRecipeTool:
    """Execute exact catalog recipes and retain bounded receipt lookup for revision."""

    def __init__(
        self,
        *,
        provider: TelemetryEvidenceProvider,
        catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
        maximum_retained_receipts: int = _MAX_RETAINED_RECEIPTS,
    ) -> None:
        if not 1 <= maximum_retained_receipts <= _MAX_RETAINED_RECEIPTS:
            raise ValueError("maximum_retained_receipts is outside the supported bound")
        self._provider = provider
        self._catalog = catalog
        self._maximum_retained = maximum_retained_receipts
        self._receipts: OrderedDict[str, TelemetryEvidenceReceipt] = OrderedDict()
        self._in_flight: dict[str, asyncio.Task[TelemetryEvidenceReceipt]] = {}
        self._lock = asyncio.Lock()

    async def run(self, need: TelemetryEvidenceNeed) -> TelemetryEvidenceReceipt:
        """Run one need once per content id and validate the provider receipt."""

        recipe = self._catalog.get(need.recipe_id, need.recipe_version)
        if need.expected_output_schema_digest != recipe.output_schema_digest:
            raise ValueError("telemetry recipe tool output schema does not match the catalog")
        async with self._lock:
            retained = self._receipts.get(need.need_id)
            if retained is not None:
                self._receipts.move_to_end(need.need_id)
                return retained
            task = self._in_flight.get(need.need_id)
            if task is None:
                task = asyncio.create_task(self._provider.gather(need))
                self._in_flight[need.need_id] = task
        try:
            receipt = await task
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            if task.done():
                async with self._lock:
                    self._in_flight.pop(need.need_id, None)
        self._validate_receipt(need, receipt)
        async with self._lock:
            prior = self._receipts.get(need.need_id)
            if prior is not None and prior != receipt:
                raise RuntimeError("telemetry provider changed an idempotent receipt")
            self._receipts[need.need_id] = receipt
            self._receipts.move_to_end(need.need_id)
            while len(self._receipts) > self._maximum_retained:
                self._receipts.popitem(last=False)
        return receipt

    def receipt(self, receipt_digest: str) -> TelemetryEvidenceReceipt | None:
        """Return a retained receipt by opaque digest for Forseti revision."""

        return next(
            (
                item
                for item in reversed(self._receipts.values())
                if item.receipt_digest == receipt_digest
            ),
            None,
        )

    @staticmethod
    def _validate_receipt(
        need: TelemetryEvidenceNeed,
        receipt: TelemetryEvidenceReceipt,
    ) -> None:
        if (
            receipt.need_id != need.need_id
            or receipt.recipe_id != need.recipe_id
            or receipt.recipe_version != need.recipe_version
            or receipt.resource_ref != need.resource_ref
            or receipt.evidence_cutoff != need.evidence_cutoff
        ):
            raise ValueError("telemetry provider receipt does not match the evidence need")
        if receipt.queried_route_count > need.max_query_count:
            raise ValueError("telemetry provider exceeded the query budget")
        if receipt.actual_cost_units > need.max_cost_units:
            raise ValueError("telemetry provider exceeded the cost budget")


__all__ = ["TelemetryEvidenceRecipeTool"]
