"""Independent post-effect observation for ``ops.start-vm@1.0.0``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kinetics import MutationEffectKind
from fdai.core.ontology_platform.reconciliation_binding import (
    ResolvedReconciliationArtifacts,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    EffectEvidenceAuthority,
    EffectObservationEnvelope,
    ObservedEffectRecord,
)
from fdai.core.ontology_platform.reconciliation_producer import (
    ExecutedActionObservation,
)
from fdai.delivery.azure.executed_action_observation import (
    AzureObservationContextIssuer,
)
from fdai.delivery.azure.vm_power_state import AzureVmPowerStateSource
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_ACTION_TYPE = "ops.start-vm"
_ACTION_VERSION = "1.0.0"
_EXPECTED_PROPERTY = "power_state"
_EXPECTED_VALUE = "running"
_IN_PROGRESS_STATE = "starting"


class AzureVmStartObservationCollector:
    """Collect one exact VM power-state observation without execution authority."""

    def __init__(
        self,
        *,
        source: AzureVmPowerStateSource,
        context_issuer: AzureObservationContextIssuer,
        observer_identity: str,
        source_identity: str,
        observation_window: timedelta = timedelta(seconds=300),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not observer_identity.strip() or not source_identity.strip():
            raise ValueError("VM start observation identities MUST be non-empty")
        if observer_identity.casefold() == source_identity.casefold():
            raise ValueError("VM start observer and source identities MUST be distinct")
        if observation_window <= timedelta(0):
            raise ValueError("VM start observation window MUST be positive")
        self._source = source
        self._context_issuer = context_issuer
        self._observer_identity = observer_identity
        self._source_identity = source_identity
        self._observation_window = observation_window
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
        """Return signed provider evidence only for an executed exact VM start."""

        del execution_receipt_ref
        if action.action_type != _ACTION_TYPE or action.mode is Mode.SHADOW:
            return None
        if execution_outcome != "succeeded":
            return None
        execution_completed_at = _aware_utc(
            execution_completed_at,
            name="execution_completed_at",
        )
        if action.executor_identity_ref is None:
            raise ValueError("VM start observation requires the executor identity")
        if action.action_type_ref is None or (
            action.action_type_ref.name != _ACTION_TYPE
            or action.action_type_ref.version != _ACTION_VERSION
        ):
            raise ValueError("VM start Action reference MUST be ops.start-vm@1.0.0")
        if (
            artifacts.action_type.name != _ACTION_TYPE
            or artifacts.action_type.version != _ACTION_VERSION
        ):
            raise ValueError("VM start artifacts MUST use ops.start-vm@1.0.0")
        plan = artifacts.plan
        if plan.schema_version != "2.0.0" or len(plan.targets) != 1:
            raise ValueError("VM start observation requires one exact semantic V2 target")
        target = plan.targets[0]
        if target.object_id.casefold() != action.target_resource_ref.casefold():
            raise ValueError("VM start observation target does not match its Action")
        expected = tuple(plan.expected_effects)
        if (
            len(expected) != 1
            or expected[0].kind is not MutationEffectKind.EXPECTED_PROPERTY
            or expected[0].target_id != target.object_id
            or expected[0].property_name != _EXPECTED_PROPERTY
            or expected[0].value != _EXPECTED_VALUE
        ):
            raise ValueError("VM start observation requires power_state == running")
        reading = await self._source.observe(
            resource_ref=target.object_id,
            target_revision=target.revision,
        )
        if reading.resource_ref.casefold() != target.object_id.casefold():
            raise ValueError("VM start power-state source substituted the target")
        if reading.target_revision != target.revision:
            raise ValueError("VM start power-state source substituted target revision")
        now = _aware_utc(self._clock(), name="clock")
        if (
            reading.observed_at < execution_completed_at
            or reading.observed_at > reading.recorded_at
            or reading.recorded_at > now
        ):
            return None
        if (
            reading.state == _IN_PROGRESS_STATE
            and reading.complete
            and not reading.conflicts
            and not reading.censoring_refs
        ):
            return None
        records: tuple[ObservedEffectRecord, ...] = ()
        if reading.state is not None:
            record = OntologyObjectRecord(
                id=target.object_id,
                object_type=target.type_ref.name,
                properties={_EXPECTED_PROPERTY: reading.state},
                revision=reading.target_revision,
                type_ref=target.type_ref,
            )
            records = (ObservedEffectRecord.from_record(record),)
        evidence = EffectObservationEnvelope.create(
            correlation_id=correlation_id,
            plan_digest=plan.digest,
            ontology_release_ref=artifacts.active_release.ref(),
            action_type_ref=plan.action_type_ref,
            owner_agent="heimdall",
            observer_identity=self._observer_identity,
            execution_identity=action.executor_identity_ref,
            source_identity=self._source_identity,
            source_authority=EffectEvidenceAuthority.PROVIDER,
            observed_at=reading.observed_at,
            observation_cutoff=reading.observed_at,
            recorded_at=reading.recorded_at,
            fresh_until=reading.fresh_until,
            complete=reading.complete,
            synthetic=False,
            conflicts=reading.conflicts,
            censoring_refs=reading.censoring_refs,
            evidence_refs=reading.evidence_refs,
            records=records,
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
            raise ValueError("VM start observation signed context does not match evidence")
        return ExecutedActionObservation(
            evidence=evidence,
            observation_context=context,
            deadline=execution_completed_at + self._observation_window,
            evaluated_at=now,
        )


def _aware_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"VM start observation {name} MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["AzureVmStartObservationCollector"]
