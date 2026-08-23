"""Independent Azure Container Apps scale-out effect observation."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.ontology_platform.kinetics import MutationEffectKind
from fdai.core.ontology_platform.reconciliation_binding import (
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    ObservedEffectRecord,
)
from fdai.core.ontology_platform.reconciliation_producer import ExecutedActionObservation
from fdai.delivery.azure.operational_evidence import AzureOperationalSnapshotSource
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_ACTION_TYPE = "ops.scale-out"
_RESOURCE_TYPE = "microsoft.app/containerapps"


class AzureObservationContextIssuer(Protocol):
    """Issue an independently signed context for one Azure observation envelope."""

    async def issue(
        self,
        *,
        evidence: EffectObservationEnvelope,
    ) -> AuthenticatedObservationContext: ...


class AzureContainerAppScaleOutObservationCollector:
    """Collect exact plan-declared Container Apps scale-out properties."""

    def __init__(
        self,
        *,
        snapshots: AzureOperationalSnapshotSource,
        context_issuer: AzureObservationContextIssuer,
        observer_identity: str,
        source_identity: str,
        observation_window: timedelta = timedelta(minutes=15),
        max_snapshot_age: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not observer_identity or not source_identity:
            raise ValueError("Azure effect observation identities MUST be non-empty")
        if observation_window <= timedelta(0) or max_snapshot_age <= timedelta(0):
            raise ValueError("Azure effect observation timing bounds MUST be positive")
        self._snapshots = snapshots
        self._context_issuer = context_issuer
        self._observer_identity = observer_identity
        self._source_identity = source_identity
        self._observation_window = observation_window
        self._max_snapshot_age = max_snapshot_age
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def collect(
        self,
        *,
        action: Action,
        artifacts: ResolvedReconciliationArtifacts,
        execution_outcome: str,
        execution_completed_at: datetime,
        execution_receipt_ref: str | None,
        correlation_id: str,
    ) -> ExecutedActionObservation | None:
        del execution_receipt_ref
        if action.action_type != _ACTION_TYPE or action.mode is Mode.SHADOW:
            return None
        if execution_outcome != "succeeded":
            return None
        if execution_completed_at.tzinfo is None or execution_completed_at.utcoffset() is None:
            raise ValueError("Azure effect observation completion time MUST be timezone-aware")
        execution_completed_at = execution_completed_at.astimezone(UTC)
        if action.executor_identity_ref is None:
            raise ValueError("Azure effect observation requires the exact executor identity")
        plan = artifacts.plan
        if plan.schema_version != "2.0.0" or len(plan.targets) != 1:
            raise ValueError("Azure effect observation requires one exact semantic V2 target")
        target = plan.targets[0]
        if target.object_id != action.target_resource_ref:
            raise ValueError("Azure effect observation target does not match its Action")
        expected = tuple(plan.expected_effects)
        if not expected or any(
            item.kind is not MutationEffectKind.EXPECTED_PROPERTY
            or item.target_id != target.object_id
            or not item.property_name
            for item in expected
        ):
            raise ValueError("Azure effect observation requires exact expected properties")
        snapshot = await self._snapshots.get(target.object_id)
        if snapshot is None:
            return None
        if (
            snapshot.resource_ref.casefold() != target.object_id.casefold()
            or snapshot.resource_type.casefold() != _RESOURCE_TYPE
        ):
            raise ValueError("Azure effect observation snapshot target or type changed")
        if snapshot.resource_revision is None:
            raise ValueError("Azure effect observation snapshot lacks a resource revision")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Azure effect observation clock MUST be timezone-aware")
        if not execution_completed_at <= snapshot.observed_at <= now:
            return None
        if now - snapshot.observed_at > self._max_snapshot_age:
            return None
        deadline = execution_completed_at + self._observation_window
        if snapshot.observed_at > deadline:
            return None
        properties: dict[str, float] = {}
        for effect in expected:
            property_name = effect.property_name
            if property_name is None:  # pragma: no cover - guarded above
                raise RuntimeError("expected property name disappeared")
            value = snapshot.metric_values.get(property_name)
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(float(value))
            ):
                return None
            properties[property_name] = float(value)
        record = OntologyObjectRecord(
            id=target.object_id,
            object_type=target.type_ref.name,
            properties=properties,
            revision=snapshot.resource_revision,
            type_ref=target.type_ref,
        )
        evidence = EffectObservationEnvelope.create(
            correlation_id=correlation_id,
            plan_digest=plan.digest,
            ontology_release_ref=artifacts.active_release.ref(),
            action_type_ref=plan.action_type_ref,
            owner_agent="heimdall",
            observer_identity=self._observer_identity,
            execution_identity=action.executor_identity_ref,
            source_identity=self._source_identity,
            source_authority=EffectEvidenceAuthority.TELEMETRY,
            observed_at=snapshot.observed_at,
            observation_cutoff=snapshot.observed_at,
            recorded_at=now,
            fresh_until=snapshot.observed_at + self._max_snapshot_age,
            complete=True,
            synthetic=False,
            conflicts=(),
            censoring_refs=(),
            evidence_refs=snapshot.evidence_refs,
            records=(ObservedEffectRecord.from_record(record),),
        )
        context = await self._context_issuer.issue(evidence=evidence)
        if (
            context.source_authority is not evidence.source_authority
            or context.observer_identity != evidence.observer_identity
            or context.executor_identity != evidence.execution_identity
            or context.source_identity != evidence.source_identity
            or context.verification_receipt.observation_id != evidence.observation_id
            or context.verification_receipt.observation_digest != evidence.content_digest()
        ):
            raise ValueError("Azure effect observation signed context does not match evidence")
        return ExecutedActionObservation(
            evidence=evidence,
            observation_context=context,
            deadline=deadline,
            evaluated_at=now,
        )


__all__ = [
    "AzureContainerAppScaleOutObservationCollector",
    "AzureObservationContextIssuer",
]
