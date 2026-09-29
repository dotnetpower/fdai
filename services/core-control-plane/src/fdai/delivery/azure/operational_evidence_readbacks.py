"""Azure-backed source records for operational-evidence readbacks."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol


class AzureMonitorMetricSampleClient(Protocol):
    """Read one exact Azure Monitor metric sample using an externally supplied credential."""

    async def sample(
        self,
        *,
        target_ref: str,
        metric_name: str,
        dimensions: Mapping[str, str],
        aggregation: str,
        observed_at: datetime,
    ) -> Mapping[str, object] | None: ...


class OperatingScopeObservationReader(Protocol):
    """Read operating-scope coverage, dependency health, and protected-signal policy."""

    async def scope_state(
        self, *, target_ref: str, signal_code: str, policy_revision: str
    ) -> Mapping[str, object] | None: ...


class AzureMonitorTestObservationProvider:
    """Verifier-identity Azure Monitor observation adapter with no token retention."""

    def __init__(
        self,
        *,
        metrics: AzureMonitorMetricSampleClient,
        scope: OperatingScopeObservationReader,
        source_anchor: str,
    ) -> None:
        self._metrics = metrics
        self._scope = scope
        self._source_anchor = source_anchor

    async def observation(self, **coordinates: str) -> Mapping[str, object] | None:
        target_ref = coordinates["target_ref"]
        signal_code = coordinates["signal_code"]
        observed_at = datetime.fromisoformat(coordinates["observed_at"].replace("Z", "+00:00"))
        scope = await self._scope.scope_state(
            target_ref=target_ref,
            signal_code=signal_code,
            policy_revision=coordinates.get("policy_revision", ""),
        )
        if scope is None:
            return None
        metric_name = str(scope.get("metric_name") or signal_code)
        raw_dimensions = scope.get("dimensions")
        dimensions = (
            {str(key): str(value) for key, value in raw_dimensions.items()}
            if isinstance(raw_dimensions, Mapping)
            else {}
        )
        aggregation = str(scope.get("aggregation") or "avg")
        sample = await self._metrics.sample(
            target_ref=target_ref,
            metric_name=metric_name,
            dimensions=dimensions,
            aggregation=aggregation,
            observed_at=observed_at,
        )
        if sample is None:
            return None
        value = sample.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("Azure Monitor sample value is invalid")
        return {
            "target_ref": target_ref,
            "access_scope_digest": str(scope["access_scope_digest"]),
            "signal_code": signal_code,
            "observed_value": float(value),
            "observed_at": observed_at.isoformat(),
            "service_impact": str(scope.get("service_impact", "unknown")),
            "protected_signal": bool(scope.get("protected_signal", True)),
            "metric_name": metric_name,
            "dimensions": dimensions,
            "aggregation": aggregation,
            "operating_scope_coverage": str(scope.get("operating_scope_coverage", "partial")),
            "dependency_health": str(scope.get("dependency_health", "unknown")),
            "policy_revision": str(scope.get("policy_revision", "")),
            "source_anchor": self._source_anchor,
        }


__all__ = [
    "AzureMonitorMetricSampleClient",
    "AzureMonitorTestObservationProvider",
    "OperatingScopeObservationReader",
]
