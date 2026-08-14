"""Post-execution producer for exact semantic effect-reconciliation requests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fdai.core.ontology_platform.action_plans import validate_action_plan_semantics
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.reconciliation_contracts import EffectReconciliationRequest
from fdai.core.ontology_platform.reconciliation_events import EffectReconciliationRequestEvent
from fdai.core.ontology_platform.reconciliation_producer import (
    ExecutedActionObservationSource,
    ExecutedActionReconciliationArtifactSource,
    ReconciliationRequestProduction,
    ReconciliationRequestProductionStatus,
)
from fdai.core.ontology_platform.reconciliation_request_outbox import (
    ReconciliationRequestOutbox,
    ReconciliationRequestOutboxState,
)
from fdai.shared.contracts.models import Action

from .reconciliation_request_publication import EffectReconciliationRequestPublisher


class EffectReconciliationRequestProducer:
    """Publish one exact observation request without fabricating a legacy plan."""

    def __init__(
        self,
        *,
        outbox: ReconciliationRequestOutbox,
        publisher: EffectReconciliationRequestPublisher,
        artifact_source: ExecutedActionReconciliationArtifactSource,
        observation_source: ExecutedActionObservationSource,
        clock: Callable[[], datetime],
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._artifact_source = artifact_source
        self._observation_source = observation_source
        self._clock = clock

    async def __call__(
        self,
        action: Action,
        execution_outcome: str,
        execution_receipt_ref: str | None,
    ) -> ReconciliationRequestProduction:
        """Publish after broker acknowledgement or return an explicit non-published state."""
        if execution_outcome not in {
            "published",
            "already_existed",
            "publish_outcome_unknown",
            "dispatched",
            "already_applied",
            "stopped",
            "failed",
        }:
            return ReconciliationRequestProduction(
                ReconciliationRequestProductionStatus.NOT_APPLICABLE,
                "execution_outcome_has_no_possible_effect",
            )
        artifacts = await self._artifact_source.resolve(action)
        if artifacts is None:
            return ReconciliationRequestProduction(
                ReconciliationRequestProductionStatus.NOT_APPLICABLE,
                "semantic_v2_plan_unavailable",
            )
        plan = artifacts.plan
        if plan.schema_version != "2.0.0":
            raise ValueError("effect reconciliation requires an existing semantic V2 plan")
        validate_action_plan_semantics(
            action_type=artifacts.action_type,
            release=artifacts.active_release,
            plan=plan,
        )
        if (
            action.action_type != artifacts.action_type.name
            or action.operation != artifacts.action_type.operation.value
            or action.action_type_ref != plan.action_type_ref
            or tuple(target.object_id for target in plan.targets) != (action.target_resource_ref,)
            or plan.arguments_digest != ontology_function_digest(action.params)
        ):
            raise ValueError("semantic V2 plan does not match the executed Action")
        correlation_id = str(action.action_id)
        observation = await self._observation_source.observe(
            action=action,
            artifacts=artifacts,
            execution_outcome=execution_outcome,
            execution_receipt_ref=execution_receipt_ref,
            correlation_id=correlation_id,
        )
        if observation is None:
            return ReconciliationRequestProduction(
                ReconciliationRequestProductionStatus.HELD,
                "independent_observation_unavailable",
            )
        request = EffectReconciliationRequest.create(
            correlation_id=correlation_id,
            plan=plan,
            action_type=artifacts.action_type,
            evidence=observation.evidence,
            deadline=observation.deadline,
            evaluated_at=observation.evaluated_at,
        )
        event = EffectReconciliationRequestEvent.from_request(
            request,
            observation_context=observation.observation_context,
        )
        await self._outbox.commit(
            event,
            available_at=self._clock(),
        )
        published = await self._publisher.publish(event.observation_attempt_id)
        if published is None:
            state = await self._outbox.state_of(event.observation_attempt_id)
            if state is not ReconciliationRequestOutboxState.PUBLISHED:
                return ReconciliationRequestProduction(
                    ReconciliationRequestProductionStatus.HELD,
                    "durably_queued",
                    event.reconciliation_id,
                )
            return ReconciliationRequestProduction(
                ReconciliationRequestProductionStatus.PUBLISHED,
                "already_broker_acknowledged",
                event.reconciliation_id,
            )
        return ReconciliationRequestProduction(
            ReconciliationRequestProductionStatus.PUBLISHED,
            "broker_acknowledged",
            event.reconciliation_id,
        )


__all__ = [
    "EffectReconciliationRequestProducer",
]
