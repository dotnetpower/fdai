"""Configuration-driven execution-mode selection before cloud I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.core.read_investigation.latency import PlanLatencyEstimate
from fdai.core.read_investigation.models import ReadInvestigationPlan


class ReadInvestigationExecutionMode(StrEnum):
    DIRECT = "direct"
    STREAMED = "streamed"
    DETACHED = "detached"


@dataclass(frozen=True, slots=True)
class InvestigationExecutionPolicy:
    direct_max_ms: int = 4_000
    streamed_max_ms: int = 15_000
    minimum_profile_samples: int = 20
    detach_on_multi_source: bool = True

    def __post_init__(self) -> None:
        if self.direct_max_ms < 1:
            raise ValueError("direct_max_ms MUST be positive")
        if self.streamed_max_ms <= self.direct_max_ms:
            raise ValueError("streamed_max_ms MUST exceed direct_max_ms")
        if self.minimum_profile_samples < 1:
            raise ValueError("minimum_profile_samples MUST be positive")

    def select(
        self,
        plan: ReadInvestigationPlan,
        estimate: PlanLatencyEstimate,
    ) -> ReadInvestigationExecutionMode:
        if plan.request.explicit_deep:
            return ReadInvestigationExecutionMode.DETACHED
        if self.detach_on_multi_source and estimate.multi_source:
            return ReadInvestigationExecutionMode.DETACHED
        if estimate.upper_ms <= self.direct_max_ms:
            return ReadInvestigationExecutionMode.DIRECT
        if estimate.upper_ms <= self.streamed_max_ms:
            return ReadInvestigationExecutionMode.STREAMED
        return ReadInvestigationExecutionMode.DETACHED


__all__ = ["InvestigationExecutionPolicy", "ReadInvestigationExecutionMode"]
