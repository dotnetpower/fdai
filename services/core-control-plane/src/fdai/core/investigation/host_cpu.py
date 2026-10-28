"""Exact-target CPU observations with explicit, positive recovery evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fdai.core.investigation.analyzer import Aggregation, reduce_values
from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)

KIND_VIRTUAL_MACHINE = "virtual_machine"
KIND_VIRTUAL_MACHINE_SCALE_SET = "virtual_machine_scale_set"
METRIC_HOST_CPU_PERCENT = "host.cpu.percent"
METRIC_VMSS_CPU_PERCENT = "host.vmss.cpu.percent"
HOST_CPU_ASSESSOR = "core.investigation.host_cpu"
_METRICS = {
    KIND_VIRTUAL_MACHINE: METRIC_HOST_CPU_PERCENT,
    KIND_VIRTUAL_MACHINE_SCALE_SET: METRIC_VMSS_CPU_PERCENT,
}


@dataclass(frozen=True, slots=True)
class HostCpuPolicy:
    """Additive host policy; existing generic threshold analyzers are unchanged.

    The default reducer remains peak/GTE, not a sustained-CPU claim. Recovery
    additionally needs a fresh, complete cadence across the requested window.
    """

    threshold_percent: float = 90.0
    aggregation: Aggregation = Aggregation.MAX
    max_age_seconds: float = 180.0
    sample_period_seconds: float = 60.0
    query_timeout_seconds: float = 15.0
    max_points: int = 1024

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold_percent) or not 0 <= self.threshold_percent <= 100:
            raise ValueError("host CPU threshold MUST be a finite percentage")
        if not isinstance(self.aggregation, Aggregation) or self.aggregation not in {
            Aggregation.MAX,
            Aggregation.AVG,
            Aggregation.LAST,
        }:
            raise ValueError("host CPU aggregation MUST be max, avg or last")
        for value in (
            self.max_age_seconds,
            self.sample_period_seconds,
            self.query_timeout_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("host CPU timing policy MUST be finite and positive")
        if type(self.max_points) is not int or not 1 <= self.max_points <= 10_000:
            raise ValueError("host CPU point limit MUST be between 1 and 10000")


def assess_host_cpu(
    points: Sequence[MetricPoint],
    *,
    resource_ref: str,
    metric_name: str,
    since: datetime,
    until: datetime,
    policy: HostCpuPolicy,
    unavailable_reason: str | None = None,
    prior_fault_at: datetime | None = None,
    prior_finding_ref: str | None = None,
) -> FindingAssessment:
    """Canonical deterministic reducer; no metric absence can close recovery."""

    if since.tzinfo is None or until.tzinfo is None or since >= until:
        raise ValueError("host CPU window MUST be aware and positive")
    if prior_fault_at is not None and prior_fault_at.tzinfo is None:
        raise ValueError("host CPU prior fault timestamp MUST be aware")
    gaps: list[str] = []
    if unavailable_reason is not None:
        return FindingAssessment(
            assessed_by=HOST_CPU_ASSESSOR,
            evidence_complete=False,
            recovery_closed=None,
            status=unavailable_reason,
            evidence_gaps=(unavailable_reason,),
        )
    if not points:
        gaps.append("metrics_missing")
    elif len(points) > policy.max_points:
        gaps.append("point_limit")
    elif any(
        point.metric_name != metric_name
        or point.labels.get("resource_id") != resource_ref
        or point.at.tzinfo is None
        or point.at.utcoffset() is None
        or not math.isfinite(point.value)
        or not 0 <= point.value <= 100
        for point in points
    ):
        gaps.append("metric_identity_or_value_invalid")
    else:
        ordered = sorted(points, key=lambda point: point.at)
        if any(point.at < since or point.at > until for point in ordered):
            gaps.append("metric_time_outside_window")
        elif (
            len({point.at for point in ordered}) != len(ordered)
            or len({tuple(sorted(point.labels.items())) for point in ordered}) != 1
        ):
            gaps.append("metric_series_ambiguous")
        elif (until - ordered[-1].at).total_seconds() > policy.max_age_seconds:
            gaps.append("stale")
        else:
            cadence = policy.sample_period_seconds
            if (
                (ordered[0].at - since).total_seconds() > cadence
                or (until - ordered[-1].at).total_seconds() > cadence
                or any(
                    (right.at - left.at).total_seconds() > cadence
                    for left, right in zip(ordered, ordered[1:], strict=False)
                )
            ):
                gaps.append("metric_window_incomplete")
            value = cast(
                float, reduce_values([point.value for point in ordered], policy.aggregation)
            )
            breached = value >= policy.threshold_percent
            recovered = (
                not breached
                and not gaps
                and bool(prior_finding_ref)
                and prior_fault_at is not None
                and ordered[-1].at > prior_fault_at
            )
            return FindingAssessment(
                assessed_by=HOST_CPU_ASSESSOR,
                evidence_complete=not gaps,
                recovery_closed=(
                    False if breached else (recovered if prior_finding_ref and not gaps else None)
                ),
                status="cpu_threshold_observed"
                if breached
                else ("cpu_below_threshold" if not gaps else "insufficient_evidence"),
                recovery_status="fresh_cpu_below_threshold" if recovered else "not_verified",
                evidence_gaps=tuple(gaps),
            )
    return FindingAssessment(
        assessed_by=HOST_CPU_ASSESSOR,
        evidence_complete=False,
        recovery_closed=None,
        status=unavailable_reason or (gaps[0] if gaps else "insufficient_evidence"),
        evidence_gaps=tuple(gaps),
    )


class HostCpuAnalyzer:
    """Query the existing MetricProvider seam without action or restart authority."""

    def __init__(
        self,
        provider: MetricProvider,
        *,
        resource_kind: str = KIND_VIRTUAL_MACHINE,
        policy: HostCpuPolicy | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if resource_kind not in _METRICS:
            raise ValueError("host CPU analyzer MUST select VM or VMSS kind")
        self._provider = provider
        self._kind = resource_kind
        self._metric = _METRICS[resource_kind]
        self._policy = policy or HostCpuPolicy()
        self._clock = wall_clock or (lambda: datetime.now(UTC))

    @property
    def resource_kind(self) -> str:
        return self._kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        return await self._analyze(resource_ref=resource_ref, window_seconds=window_seconds)

    async def analyze_recovery(
        self,
        *,
        prior_finding: AnalyzerFinding,
        finding_ref: str,
        window_seconds: float,
    ) -> Sequence[AnalyzerFinding]:
        """Only a caller-held active fault plus later positive samples can recover."""

        if (
            not finding_ref.strip()
            or prior_finding.resource_kind != self._kind
            or prior_finding.signal != "host_cpu"
            or prior_finding.assessment is None
            or prior_finding.assessment.assessed_by != HOST_CPU_ASSESSOR
            or prior_finding.assessment.recovery_closed is True
            or prior_finding.assessment.status != "cpu_threshold_observed"
        ):
            raise ValueError("host CPU recovery MUST reference a prior actual fault Finding")
        return await self._analyze(
            resource_ref=prior_finding.resource_ref,
            window_seconds=window_seconds,
            prior_finding=prior_finding,
            finding_ref=finding_ref,
        )

    async def _analyze(
        self,
        *,
        resource_ref: str,
        window_seconds: float,
        prior_finding: AnalyzerFinding | None = None,
        finding_ref: str | None = None,
    ) -> Sequence[AnalyzerFinding]:
        if not resource_ref or not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("host CPU target and finite positive window MUST be supplied")
        until = self._clock()
        since = until - timedelta(seconds=window_seconds)
        points: list[MetricPoint] = []
        unavailable: str | None = None
        query = MetricQuery(
            metric_name=self._metric,
            labels={"resource_id": resource_ref},
            since=since,
            until=until,
            aggregation=self._policy.aggregation.value,
        )
        try:
            async with asyncio.timeout(self._policy.query_timeout_seconds):
                async for point in self._provider.query(query):
                    points.append(point)
                    if len(points) > self._policy.max_points:
                        unavailable = "point_limit"
                        break
        except MetricProviderError as exc:
            unavailable = (
                "authorization_denied" if exc.http_status in {401, 403} else "source_unavailable"
            )
        except TimeoutError:
            unavailable = "source_timeout"
        except Exception:  # noqa: BLE001 - partial provider output cannot prove recovery
            unavailable = "source_unavailable"
        assessment = assess_host_cpu(
            points,
            resource_ref=resource_ref,
            metric_name=self._metric,
            since=since,
            until=until,
            policy=self._policy,
            unavailable_reason=unavailable,
            prior_fault_at=prior_finding.occurred_at if prior_finding else None,
            prior_finding_ref=finding_ref,
        )
        if prior_finding is None and assessment.status == "cpu_below_threshold":
            return ()
        # Preserve replay equivalence without copying provider identities or dimensions.
        replay = json.dumps(
            {
                "resource_ref": resource_ref,
                "metric_name": self._metric,
                "since": since.isoformat(),
                "until": until.isoformat(),
                "policy": asdict(self._policy),
                "unavailable_reason": unavailable,
                "prior_fault_at": prior_finding.occurred_at.isoformat() if prior_finding else None,
                "prior_finding_ref": finding_ref,
                "points": [
                    {
                        "metric_name": (
                            self._metric
                            if point.metric_name == self._metric
                            else "unexpected_metric"
                        ),
                        "at": point.at.isoformat(),
                        "value": point.value if math.isfinite(point.value) else str(point.value),
                        "labels": {
                            "resource_id": resource_ref
                            if point.labels.get("resource_id") == resource_ref
                            else "identity-mismatch",
                            "series_digest": hashlib.sha256(
                                json.dumps(sorted(point.labels.items())).encode()
                            ).hexdigest(),
                        },
                    }
                    for point in points
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(replay.encode()).hexdigest()
        breached = assessment.status == "cpu_threshold_observed"
        return (
            AnalyzerFinding(
                resource_ref=resource_ref,
                resource_kind=self._kind,
                signal="host_cpu",
                observation=(
                    f"Host CPU observation: {assessment.status}; configured "
                    f"{self._policy.aggregation.value} threshold "
                    f"{self._policy.threshold_percent:g} percent. No cause or action is inferred."
                ),
                severity=Severity.HIGH if breached else Severity.LOW,
                occurred_at=until,
                evidence_refs=tuple(
                    ref for ref in (f"host-cpu-observation:sha256:{digest}", finding_ref) if ref
                ),
                metadata={"assessment_input": replay},
                assessment=assessment,
            ),
        )
