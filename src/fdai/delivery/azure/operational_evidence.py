"""Azure operational evidence adapters over current inventory and metric seams."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fdai.core.assurance_twin import DynamicSimulationRequest, SimulationBranch, SimulationSnapshot
from fdai.core.case_history import FailureFingerprint
from fdai.core.detection.series import MetricSample
from fdai.core.rca import TemporalCausalEvidence, TemporalSeries
from fdai.core.tiers.t1_lightweight import (
    CurrentReuseVerification,
    LearnedAction,
    OperationalCaseContext,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.metric import MetricPoint, MetricProvider, MetricQuery
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_MAX_POINTS = 512
_MAX_EVIDENCE_REFS = 64
_MAX_BRANCHES = 32
_MAX_CONTEXT_ITEMS = 32
_MAX_TEMPORAL_LOOKBACK = timedelta(days=31)


@dataclass(frozen=True, slots=True)
class AzureOperationalSnapshot:
    """One time-consistent current graph view for an Azure target."""

    resource_ref: str
    resource_type: str
    topology_roles: tuple[str, ...]
    ownership_shape: tuple[str, ...]
    graph_digest: str
    owner_digest: str
    observed_at: datetime
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.resource_ref or not self.resource_type:
            raise ValueError("Azure operational snapshot identity MUST be non-empty")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("Azure operational snapshot observed_at MUST be timezone-aware")
        for value in (self.graph_digest, self.owner_digest, *self.evidence_refs):
            if not _is_digest(value):
                raise ValueError("Azure operational snapshot digests MUST be SHA-256")
        if not 1 <= len(self.evidence_refs) <= _MAX_EVIDENCE_REFS:
            raise ValueError("Azure operational snapshot evidence refs MUST be bounded")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Azure operational snapshot evidence refs MUST be unique")
        for name, values in (
            ("topology_roles", self.topology_roles),
            ("ownership_shape", self.ownership_shape),
        ):
            if (
                not 1 <= len(values) <= _MAX_CONTEXT_ITEMS
                or len(set(values)) != len(values)
                or any(not value or len(value) > 128 for value in values)
            ):
                raise ValueError(f"Azure operational snapshot {name} MUST be bounded and unique")


class AzureOperationalSnapshotSource(Protocol):
    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None: ...


AzureInventoryContextReader = Callable[[str], Awaitable[Mapping[str, object] | None]]


class AzureCachedOperationalSnapshotSource:
    """Load a strict operational manifest from the promoted inventory cache."""

    def __init__(self, reader: AzureInventoryContextReader) -> None:
        self._reader = reader

    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        value = await self._reader(resource_ref)
        if value is None:
            return None
        props = value.get("props")
        if not isinstance(props, Mapping):
            raise ValueError("Azure inventory context props MUST be an object")
        context = props.get("operational_context")
        if not isinstance(context, Mapping):
            raise ValueError("Azure inventory context lacks operational_context")
        expected = {
            "topology_roles",
            "ownership_shape",
            "graph_digest",
            "owner_digest",
            "observed_at",
            "evidence_refs",
        }
        if set(context) != expected:
            raise ValueError("Azure inventory operational_context has unexpected fields")
        resource_id = value.get("resource_id")
        resource_type = value.get("resource_type")
        if not isinstance(resource_id, str) or not isinstance(resource_type, str):
            raise ValueError("Azure inventory context identity is invalid")
        return AzureOperationalSnapshot(
            resource_ref=resource_id,
            resource_type=resource_type,
            topology_roles=_string_tuple(context, "topology_roles"),
            ownership_shape=_string_tuple(context, "ownership_shape"),
            graph_digest=_required_string(context, "graph_digest"),
            owner_digest=_required_string(context, "owner_digest"),
            observed_at=_timestamp(context, "observed_at"),
            evidence_refs=_string_tuple(context, "evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class AzureReuseSafetyChecks:
    preconditions_passed: bool
    target_identity_verified: bool
    blast_radius_within_limit: bool
    policy_allowed: bool
    dry_run_passed: bool
    idempotency_available: bool
    rollback_resolved: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        checks = (
            self.preconditions_passed,
            self.target_identity_verified,
            self.blast_radius_within_limit,
            self.policy_allowed,
            self.dry_run_passed,
            self.idempotency_available,
            self.rollback_resolved,
        )
        if any(not isinstance(check, bool) for check in checks):
            raise ValueError("Azure reuse safety checks MUST be boolean")
        if not self.evidence_refs or any(not _is_digest(ref) for ref in self.evidence_refs):
            raise ValueError("Azure reuse safety evidence refs MUST contain SHA-256 values")
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS or len(set(self.evidence_refs)) != len(
            self.evidence_refs
        ):
            raise ValueError("Azure reuse safety evidence refs MUST be bounded and unique")


class AzureReuseSafetyEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        event: Event,
        action: LearnedAction,
        snapshot: AzureOperationalSnapshot,
    ) -> AzureReuseSafetyChecks: ...


class AzureCurrentReuseVerifier:
    """Recollect current Azure graph and deterministic safety evidence."""

    def __init__(
        self,
        *,
        snapshots: AzureOperationalSnapshotSource,
        safety: AzureReuseSafetyEvaluator,
        max_snapshot_age: timedelta = timedelta(minutes=5),
        max_future_skew: timedelta = timedelta(minutes=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_snapshot_age <= timedelta(0) or max_future_skew < timedelta(0):
            raise ValueError("Azure current snapshot freshness bounds are invalid")
        self._snapshots = snapshots
        self._safety = safety
        self._max_snapshot_age = max_snapshot_age
        self._max_future_skew = max_future_skew
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def verify(
        self,
        *,
        event: Event,
        action: LearnedAction,
        context: OperationalCaseContext,
    ) -> CurrentReuseVerification:
        resource_ref = _resource_ref(event)
        snapshot = await self._snapshots.get(resource_ref)
        if snapshot is None:
            raise ValueError("current Azure operational snapshot is unavailable")
        if snapshot.resource_ref.casefold() != resource_ref.casefold():
            raise ValueError("current Azure operational snapshot target changed")
        _require_current_snapshot(
            snapshot,
            evaluated_at=_evaluation_time(self._clock),
            max_age=self._max_snapshot_age,
            max_future_skew=self._max_future_skew,
            label="current Azure operational",
        )
        fingerprint = _failure_fingerprint(event)
        checks = await self._safety.evaluate(event=event, action=action, snapshot=snapshot)
        evidence_refs = tuple(sorted({*snapshot.evidence_refs, *checks.evidence_refs}))
        if len(evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("current Azure reuse evidence refs exceed their limit")
        topology_role = context.required_topology_role
        if topology_role not in snapshot.topology_roles:
            topology_role = snapshot.topology_roles[0] if snapshot.topology_roles else "unknown"
        return CurrentReuseVerification(
            case_ref=context.case_ref,
            observed_at=snapshot.observed_at,
            evidence_refs=evidence_refs,
            failure_fingerprint=fingerprint.digest,
            resource_type=snapshot.resource_type,
            topology_role=topology_role,
            graph_digest=snapshot.graph_digest,
            owner_digest=snapshot.owner_digest,
            preconditions_passed=checks.preconditions_passed,
            target_identity_verified=checks.target_identity_verified,
            blast_radius_within_limit=checks.blast_radius_within_limit,
            policy_allowed=checks.policy_allowed,
            dry_run_passed=checks.dry_run_passed,
            idempotency_available=checks.idempotency_available,
            rollback_resolved=checks.rollback_resolved,
        )


@dataclass(frozen=True, slots=True)
class AzureTemporalPolicy:
    cause_metric: str
    effect_metric: str
    mechanism: str
    required_topology_role: str
    lookback: timedelta
    topological_reachability: float = 1.0
    mechanism_fit: float = 1.0
    intervention_consistency: float = 0.0
    evidence_completeness: float = 1.0
    finding_rule_id: str = "azure.operational-evidence"
    finding_severity: str = "medium"

    def __post_init__(self) -> None:
        if not all(
            (
                self.cause_metric,
                self.effect_metric,
                self.mechanism,
                self.required_topology_role,
                self.finding_rule_id,
                self.finding_severity,
            )
        ):
            raise ValueError("Azure temporal policy identity MUST be non-empty")
        if self.lookback <= timedelta(0):
            raise ValueError("Azure temporal policy lookback MUST be positive")
        if self.lookback > _MAX_TEMPORAL_LOOKBACK:
            raise ValueError("Azure temporal policy lookback exceeds 31 days")
        scores = (
            self.topological_reachability,
            self.mechanism_fit,
            self.intervention_consistency,
            self.evidence_completeness,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in scores):
            raise ValueError("Azure temporal policy scores MUST be in [0, 1]")


class AzureTemporalCausalEvidenceProvider:
    """Build leakage-safe Azure temporal evidence from configured metrics."""

    def __init__(
        self,
        *,
        snapshots: AzureOperationalSnapshotSource,
        metrics: MetricProvider,
        policies: Mapping[str, AzureTemporalPolicy],
    ) -> None:
        if not policies:
            raise ValueError("Azure temporal evidence policies MUST be non-empty")
        self._snapshots = snapshots
        self._metrics = metrics
        self._policies = dict(policies)

    async def collect(
        self,
        *,
        event: Event,
        incident_id: str,
    ) -> TemporalCausalEvidence | None:
        policy = self._policies.get(event.event_type)
        if policy is None:
            return None
        resource_ref = _resource_ref(event)
        snapshot = await self._snapshots.get(resource_ref)
        if snapshot is None:
            return None
        if snapshot.resource_ref.casefold() != resource_ref.casefold():
            raise ValueError("Azure temporal snapshot target changed")
        if snapshot.observed_at > event.ingested_at:
            raise ValueError("Azure temporal snapshot MUST NOT cross the feature cutoff")
        if policy.required_topology_role not in snapshot.topology_roles:
            return None
        since = event.ingested_at - policy.lookback
        cause = await _metric_series(
            self._metrics,
            metric=policy.cause_metric,
            resource_ref=resource_ref,
            since=since,
            until=event.ingested_at,
        )
        effect = await _metric_series(
            self._metrics,
            metric=policy.effect_metric,
            resource_ref=resource_ref,
            since=since,
            until=event.ingested_at,
        )
        if cause is None or effect is None:
            return None
        evidence_digest = _digest(
            {
                "cause_metric": policy.cause_metric,
                "effect_metric": policy.effect_metric,
                "mechanism": policy.mechanism,
                "required_topology_role": policy.required_topology_role,
                "since": since.astimezone(UTC).isoformat(),
                "until": event.ingested_at.astimezone(UTC).isoformat(),
                "graph_revision": snapshot.graph_digest,
                "cause": [
                    (sample.timestamp.astimezone(UTC).isoformat(), sample.value)
                    for sample in cause.samples
                ],
                "effect": [
                    (sample.timestamp.astimezone(UTC).isoformat(), sample.value)
                    for sample in effect.samples
                ],
                "resource_ref": resource_ref.casefold(),
            }
        )
        evidence_refs = tuple(sorted({*snapshot.evidence_refs, evidence_digest}))
        if len(evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("Azure temporal evidence refs exceed their limit")
        finding_id = f"finding:{event.event_id}"
        evidence_id = f"evidence:{evidence_digest}"
        return TemporalCausalEvidence(
            cause=cause,
            effect=effect,
            feature_cutoff=event.ingested_at,
            evidence_refs=evidence_refs,
            cause_ref=f"metric:{policy.cause_metric}",
            effect_ref=f"event:{event.event_id}",
            mechanism=policy.mechanism,
            graph_revision=snapshot.graph_digest,
            finding_id=finding_id,
            topological_reachability=policy.topological_reachability,
            mechanism_fit=policy.mechanism_fit,
            intervention_consistency=policy.intervention_consistency,
            evidence_completeness=policy.evidence_completeness,
            supporting_evidence_ids=(evidence_id,),
            endpoint_objects=(
                OntologyObjectRecord(
                    id=finding_id,
                    object_type="Finding",
                    properties={
                        "id": finding_id,
                        "rule_id": policy.finding_rule_id,
                        "resource_id": resource_ref,
                        "severity": policy.finding_severity,
                        "evaluation_ts": event.ingested_at,
                        "context": {"event_type": event.event_type},
                    },
                ),
                OntologyObjectRecord(
                    id=evidence_id,
                    object_type="EvidenceArtifact",
                    properties={
                        "id": evidence_id,
                        "kind": "azure_metric_window",
                        "uri": f"urn:fdai:azure-evidence:{evidence_digest}",
                        "sha256": evidence_digest,
                        "status": "observed",
                        "classification": "internal",
                        "captured_at": event.ingested_at,
                    },
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class AzureDynamicPolicy:
    metric: str
    objective: Literal["minimize", "maximize"] = "minimize"
    divergence_threshold: float = 0.0
    max_snapshot_age: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("Azure Dynamic policy metric MUST be non-empty")
        if not math.isfinite(self.divergence_threshold) or self.divergence_threshold < 0.0:
            raise ValueError("Azure Dynamic divergence threshold MUST be finite and non-negative")
        if self.max_snapshot_age <= timedelta(0):
            raise ValueError("Azure Dynamic max_snapshot_age MUST be positive")


class AzureBranchEstimator(Protocol):
    async def estimate(
        self,
        *,
        event: Event,
        action: LearnedAction,
        snapshot: AzureOperationalSnapshot,
        metric: str,
    ) -> tuple[SimulationBranch, ...]: ...


class AzureDynamicSimulationRequestProvider:
    """Build bounded Dynamic requests from current Azure snapshots."""

    def __init__(
        self,
        *,
        snapshots: AzureOperationalSnapshotSource,
        estimator: AzureBranchEstimator,
        policies: Mapping[str, AzureDynamicPolicy],
        max_future_skew: timedelta = timedelta(minutes=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not policies:
            raise ValueError("Azure Dynamic policies MUST be non-empty")
        if max_future_skew < timedelta(0):
            raise ValueError("Azure Dynamic max_future_skew MUST be non-negative")
        self._snapshots = snapshots
        self._estimator = estimator
        self._policies = dict(policies)
        self._max_future_skew = max_future_skew
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> DynamicSimulationRequest | None:
        policy = self._policies.get(action.action_type)
        if policy is None:
            return None
        snapshot = await self._snapshots.get(_resource_ref(event))
        if snapshot is None:
            return None
        resource_ref = _resource_ref(event)
        if snapshot.resource_ref.casefold() != resource_ref.casefold():
            raise ValueError("Azure Dynamic snapshot target changed")
        _require_current_snapshot(
            snapshot,
            evaluated_at=_evaluation_time(self._clock),
            max_age=policy.max_snapshot_age,
            max_future_skew=self._max_future_skew,
            label="Azure Dynamic",
        )
        branches = await self._estimator.estimate(
            event=event,
            action=action,
            snapshot=snapshot,
            metric=policy.metric,
        )
        if not 1 <= len(branches) <= _MAX_BRANCHES:
            raise ValueError("Azure Dynamic estimator branches MUST be bounded")
        return DynamicSimulationRequest(
            snapshot=SimulationSnapshot(
                snapshot_id=f"azure:{snapshot.graph_digest}",
                target_digest=_digest(snapshot.resource_ref.casefold()),
                metric=policy.metric,
                observed_at=snapshot.observed_at,
            ),
            branches=branches,
            objective=policy.objective,
            divergence_threshold=policy.divergence_threshold,
        )


async def _metric_series(
    provider: MetricProvider,
    *,
    metric: str,
    resource_ref: str,
    since: datetime,
    until: datetime,
) -> TemporalSeries | None:
    points: list[MetricPoint] = []
    async for point in provider.query(
        MetricQuery(
            metric_name=metric,
            labels={"resource_id": resource_ref.casefold()},
            since=since,
            until=until,
        )
    ):
        points.append(point)
        if len(points) > _MAX_POINTS:
            raise ValueError("Azure temporal metric points exceed their limit")
    points.sort(key=lambda item: item.at)
    if any(point.at.tzinfo is None or point.at < since or point.at > until for point in points):
        raise ValueError("Azure temporal metric provider returned out-of-window points")
    if any(not math.isfinite(point.value) for point in points):
        raise ValueError("Azure temporal metric provider returned non-finite values")
    if any(
        point.metric_name != metric
        or point.labels.get("resource_id", "").casefold() != resource_ref.casefold()
        for point in points
    ):
        raise ValueError("Azure temporal metric provider returned out-of-scope points")
    if len(points) < 2 or len({point.at for point in points}) != len(points):
        return None
    return TemporalSeries(
        metric=metric,
        samples=tuple(MetricSample(timestamp=point.at, value=point.value) for point in points),
    )


def _resource_ref(event: Event) -> str:
    if event.resource_ref:
        return event.resource_ref
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping) and isinstance(resource.get("id"), str):
        return str(resource["id"])
    raise ValueError("Azure operational evidence requires an exact resource_ref")


def _evaluation_time(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("Azure operational evidence clock MUST return an aware datetime")
    return value


def _require_current_snapshot(
    snapshot: AzureOperationalSnapshot,
    *,
    evaluated_at: datetime,
    max_age: timedelta,
    max_future_skew: timedelta,
    label: str,
) -> None:
    if not (evaluated_at - max_age <= snapshot.observed_at <= evaluated_at + max_future_skew):
        raise ValueError(f"{label} snapshot is stale or future-skewed")


def _failure_fingerprint(event: Event) -> FailureFingerprint:
    value = event.payload.get("failure_fingerprint")
    if not isinstance(value, Mapping):
        raise ValueError("Azure operational reuse requires a failure_fingerprint")
    return FailureFingerprint.from_mapping(value)


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _digest(value: object) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Azure inventory operational_context {key} MUST be non-empty")
    return item


def _string_tuple(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or not item or any(not isinstance(part, str) for part in item):
        raise ValueError(f"Azure inventory operational_context {key} MUST be a string array")
    return tuple(item)


def _timestamp(value: Mapping[str, object], key: str) -> datetime:
    text = _required_string(value, key)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Azure inventory operational_context {key} MUST be timezone-aware")
    return parsed


__all__ = [
    "AzureBranchEstimator",
    "AzureCachedOperationalSnapshotSource",
    "AzureCurrentReuseVerifier",
    "AzureDynamicPolicy",
    "AzureDynamicSimulationRequestProvider",
    "AzureOperationalSnapshot",
    "AzureOperationalSnapshotSource",
    "AzureReuseSafetyChecks",
    "AzureReuseSafetyEvaluator",
    "AzureTemporalCausalEvidenceProvider",
    "AzureTemporalPolicy",
]
