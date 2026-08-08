"""Pure fail-closed reduction of startup probe evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai.core.readiness.models import (
    AuthorityCeiling,
    ProbeCriticality,
    ProbeStatus,
    ReadinessDecision,
    StartupProbeResult,
    StartupProbeSpec,
    StartupReadinessReport,
    more_restrictive,
)


def reduce_startup_readiness(
    specs: Sequence[StartupProbeSpec],
    results: Sequence[StartupProbeResult],
    *,
    generated_at: datetime,
    deployment_ceilings: Mapping[str, AuthorityCeiling] | None = None,
) -> StartupReadinessReport:
    """Reduce one complete probe pass without raising deployment authority."""
    ordered_specs = tuple(sorted(specs, key=lambda item: item.probe_id))
    if len({spec.probe_id for spec in ordered_specs}) != len(ordered_specs):
        raise ValueError("startup probe ids MUST be unique")
    result_by_id = {result.probe_id: result for result in results}
    if len(result_by_id) != len(results):
        raise ValueError("startup probe results MUST be unique by probe id")
    unknown = sorted(set(result_by_id) - {spec.probe_id for spec in ordered_specs})
    if unknown:
        raise ValueError(f"startup probe results are not configured: {', '.join(unknown)}")

    ceilings = dict(deployment_ceilings or {})
    missing: list[str] = []
    stale: list[str] = []
    blocked = False
    degraded = False

    for spec in ordered_specs:
        result = result_by_id.get(spec.probe_id)
        unavailable = result is None
        if result is None:
            missing.append(spec.probe_id)
        elif result.expires_at <= generated_at:
            stale.append(spec.probe_id)
            unavailable = True
        elif result.status is not ProbeStatus.PASSED:
            unavailable = True

        deployment_ceiling = ceilings.get(spec.capability, AuthorityCeiling.DEPLOYMENT)
        ceilings[spec.capability] = deployment_ceiling
        if not unavailable:
            continue
        ceilings[spec.capability] = more_restrictive(
            deployment_ceiling,
            spec.failure_ceiling,
        )
        if spec.criticality is ProbeCriticality.PROCESS_CRITICAL:
            blocked = True
        else:
            degraded = True

    decision = (
        ReadinessDecision.BLOCKED
        if blocked
        else ReadinessDecision.DEGRADED
        if degraded
        else ReadinessDecision.READY
    )
    return StartupReadinessReport(
        generated_at=generated_at,
        decision=decision,
        results=tuple(sorted(results, key=lambda item: item.probe_id)),
        missing_probe_ids=tuple(missing),
        stale_probe_ids=tuple(stale),
        authority_ceilings=dict(sorted(ceilings.items())),
    )


__all__ = ["reduce_startup_readiness"]
