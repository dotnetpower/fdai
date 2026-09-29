"""Readback for the ``operational-test-observation`` purpose."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass

from fdai.core.operational_context.test_context import observation_context_digest
from fdai.core.operational_evidence.trust_registry import Venue

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts

_R = OperationalEvidenceRejectionClass
PURPOSE = "operational-test-observation"
METRIC_SOURCE = "azure-monitor.metrics"
DEPENDENCY_HEALTH_SOURCE = "operating-scope.dependency-health"


class TestObservationProvider(Protocol):
    """Read one exact metric sample and dependency-health coverage."""

    async def observation(self, **coordinates: str) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class OperationalTestObservationReadback:
    """Verify metric value, scope coverage, dependency health, and protected-signal policy."""

    provider: TestObservationProvider

    purposes = frozenset({PURPOSE})

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        raw = await self.provider.observation(**context.request.locator.coordinates)
        if raw is None:
            return reject(_R.PARTIAL, "metric_sample_missing")
        required = {
            "target_ref",
            "access_scope_digest",
            "signal_code",
            "observed_value",
            "observed_at",
            "service_impact",
            "protected_signal",
            "metric_name",
            "dimensions",
            "aggregation",
            "operating_scope_coverage",
            "dependency_health",
            "policy_revision",
            "source_anchor",
        }
        allowed = required | {"conflicting_samples", "conflicting_health_sources"}
        if set(raw) - allowed or not required <= set(raw):
            return reject(_R.PARTIAL, "source_record_malformed")
        if context.venue is Venue.DEPLOYED and raw["source_anchor"] == "local-loopback":
            return reject(_R.SYNTHETIC_LIVE, "local_loopback_metric_source")
        try:
            observed_at = _timestamp(raw["observed_at"])
            observed_value = _float(raw["observed_value"])
            dimensions = _mapping(raw["dimensions"], label="dimensions")
            sample_conflicts = _strings(raw.get("conflicting_samples", ()))
            health_conflicts = _strings(raw.get("conflicting_health_sources", ()))
        except ValueError:
            return reject(_R.PARTIAL, "metric_sample_malformed")
        if sample_conflicts or health_conflicts:
            return reject(
                _R.CONFLICTING,
                "conflicting_observation_source",
                conflicts=tuple(sorted((*sample_conflicts, *health_conflicts))),
            )
        if raw["access_scope_digest"] != context.access_scope_digest:
            return reject(_R.CROSS_SCOPE, "scope_mismatch")
        if raw["policy_revision"] != context.request.lookup.source_revision:
            return reject(_R.REPLAY_SUBSTITUTED, "source_revision_mismatch")
        if raw["operating_scope_coverage"] != "complete":
            return reject(_R.PARTIAL, "operating_scope_incomplete")
        if raw["dependency_health"] != "healthy":
            return reject(_R.PARTIAL, "dependency_health_incomplete")
        if raw["protected_signal"] is not False:
            return reject(_R.PARTIAL, "protected_signal")
        if raw["service_impact"] != "none":
            return reject(_R.PARTIAL, "service_impact_not_none")
        digest = observation_context_digest(
            target_ref=str(raw["target_ref"]),
            access_scope_digest=str(raw["access_scope_digest"]),
            signal_code=str(raw["signal_code"]),
            observed_value=observed_value,
            observed_at=observed_at,
            service_impact="none",
            protected_signal=False,
        )
        if digest != context.request.lookup.evidence_digest:
            return reject(_R.REPLAY_SUBSTITUTED, "evidence_mismatch")
        return ReadbackFacts(
            evidence_digest=digest,
            source_identity=METRIC_SOURCE,
            authentication={
                "metric_name": raw["metric_name"],
                "dimensions": dimensions,
                "aggregation": raw["aggregation"],
                "source_anchor": raw["source_anchor"],
            },
            completeness={
                "operating_scope_coverage": raw["operating_scope_coverage"],
                "dependency_health": raw["dependency_health"],
                "exact_bin": observed_at.isoformat(),
            },
            conflict={
                "conflicting_samples": len(sample_conflicts),
                "conflicting_health_sources": len(health_conflicts),
            },
            provenance={
                "target_ref": raw["target_ref"],
                "policy_revision": raw["policy_revision"],
                "sources": [METRIC_SOURCE, DEPENDENCY_HEALTH_SOURCE],
            },
            event_at=observed_at,
            evidence_cutoff=context.read_at,
        )


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp expected")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return parsed


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("finite numeric value expected")
    return float(value)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("conflict digests MUST be strings")
    return tuple(value)


__all__ = [
    "DEPENDENCY_HEALTH_SOURCE",
    "METRIC_SOURCE",
    "PURPOSE",
    "OperationalTestObservationReadback",
    "TestObservationProvider",
]
