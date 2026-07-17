"""Read-only GPU cost-governance probes for chaos validation."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence

GpuSkuAssessment = Callable[
    [Sequence[str]],
    Mapping[str, object] | Awaitable[Mapping[str, object]],
]


class GpuSkuMismatchProbe:
    def __init__(
        self,
        *,
        assess: GpuSkuAssessment,
        expected_observed_sku: str,
        expected_recommended_sku: str,
        min_confidence: float = 0.8,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence MUST be in [0, 1]")
        self._assess = assess
        self._observed = expected_observed_sku
        self._recommended = expected_recommended_sku
        self._min_confidence = min_confidence

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        if signal != "gpu_sku_mismatch":
            return False
        assessment = self._assess(targets)
        if inspect.isawaitable(assessment):
            assessment = await assessment
        confidence = assessment.get("confidence")
        return (
            assessment.get("observed_sku") == self._observed
            and assessment.get("recommended_sku") == self._recommended
            and isinstance(confidence, int | float)
            and not isinstance(confidence, bool)
            and float(confidence) >= self._min_confidence
        )


__all__ = ["GpuSkuAssessment", "GpuSkuMismatchProbe"]
