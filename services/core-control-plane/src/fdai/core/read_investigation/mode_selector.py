"""Select read-investigation delivery mode from durable latency evidence."""

from __future__ import annotations

import logging

from fdai.core.read_investigation.catalog import read_tool_spec
from fdai.core.read_investigation.execution_policy import (
    InvestigationExecutionPolicy,
    ReadInvestigationExecutionMode,
)
from fdai.core.read_investigation.latency import (
    ReadLatencyProfile,
    estimate_plan_latency,
    latency_profile,
)
from fdai.core.read_investigation.models import ReadInvestigationPlan
from fdai.shared.providers.read_investigation import ReadLatencyProfileStore, ReadToolId

_LOG = logging.getLogger(__name__)


class ReadInvestigationModeSelector:
    """Choose one mode from a canonical plan without invoking a read provider."""

    def __init__(
        self,
        *,
        latency_store: ReadLatencyProfileStore,
        transport: str,
        policy: InvestigationExecutionPolicy,
    ) -> None:
        self._latency_store = latency_store
        self._transport = transport
        self._policy = policy

    async def select(self, plan: ReadInvestigationPlan) -> ReadInvestigationExecutionMode:
        """Load bounded profiles and apply the configured deterministic policy."""

        profiles: dict[ReadToolId, ReadLatencyProfile] = {}
        for step in plan.steps:
            spec = read_tool_spec(step.tool_id)
            try:
                samples = await self._latency_store.recent(
                    tool_id=step.tool_id,
                    transport=self._transport,
                    operation_class=spec.operation_class,
                    limit=self._policy.minimum_profile_samples,
                )
            except Exception as exc:  # noqa: BLE001 - cold estimates preserve bounded selection
                _LOG.warning(
                    "read_investigation_latency_profile_unavailable",
                    extra={
                        "correlation_id": plan.request.correlation_ref,
                        "tool_id": step.tool_id.value,
                        "error_kind": type(exc).__name__,
                    },
                )
                return ReadInvestigationExecutionMode.DETACHED
            profiles[step.tool_id] = latency_profile(samples)
        estimate = estimate_plan_latency(
            plan,
            profiles,
            minimum_samples=self._policy.minimum_profile_samples,
        )
        return self._policy.select(plan, estimate)


__all__ = ["ReadInvestigationModeSelector"]
