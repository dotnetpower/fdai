"""Assembled Core runtime projected into task supervision."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from fdai.core.assurance_twin.proposal_effects import (
    ReviewedActionTypeEffect,
    ReviewedEffectCatalog,
)
from fdai.delivery.assurance_twin_evidence_source import (
    AssuranceTwinEvidenceRequestRelay,
    StateStoreTwinEvidenceRepository,
)
from fdai.delivery.assurance_twin_inventory import PostgresTwinInventorySource
from fdai.delivery.assurance_twin_posture import AssuranceTwinPostureRecorder
from fdai.delivery.assurance_twin_posture_producer import (
    AssuranceTwinPostureProducer,
    CompletePostureEvaluator,
)
from fdai.delivery.assurance_twin_proposal_intake import StateStoreTypedProposalReviewIntake
from fdai.delivery.assurance_twin_publication import AssuranceTwinOutboxPublisher
from fdai.delivery.assurance_twin_review_producer import AssuranceTwinReviewProducer
from fdai.delivery.assurance_twin_writers import (
    AssuranceTwinAgentWriter,
    RetainedTwinEvidenceSource,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.runtime.bootstrap_tasks import RuntimeTaskConfiguration
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    import asyncio

    from fdai.composition import Container
    from fdai.composition.readiness import OperationalReadinessEventHandler
    from fdai.core.control_loop import ControlLoop
    from fdai.delivery.azure.diagnostic_event_ingest import DiagnosticEventIngestBridge
    from fdai.delivery.notifications import NotificationDeliveryReceiptApplier
    from fdai.delivery.runtime_settings import RuntimeSettingsService
    from fdai.runtime import bootstrap_incidents
    from fdai.runtime.bootstrap_bindings import EffectReconciliationRequestRuntimeBinding
    from fdai.runtime.bootstrap_lifecycle import DiscoveryActivationRuntime
    from fdai.runtime.bootstrap_messaging import MessagingRuntime
    from fdai.runtime.bootstrap_pantheon import PantheonInitializationResult
    from fdai.runtime.bootstrap_semantics import SemanticRuntime
    from fdai.runtime.handover_knowledge_lifecycle import HandoverKnowledgeLifecycleWorker
    from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
    from fdai.runtime.operating_intent_revalidation import (
        OperatingIntentSourceRevalidationWorker,
    )
    from fdai.runtime.readiness import StartupReadinessRuntime
    from fdai.runtime.rule_activation import RuleActivationRuntimeReconciler
    from fdai.runtime.stewardship_governance import StewardshipGovernanceWorker
    from fdai.runtime.stewardship_identity_health import StewardshipIdentityHealthWorker
    from fdai.runtime.stewardship_merge_effects import StewardshipMergeEffectsWorker
    from fdai.runtime.task_workers import TaskWorkerRuntimeBinding
    from fdai.shared.providers.hil_registry import HilWorkflowDecisionRegistry


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    """Fully assembled active runtime consumed by health and task supervision."""

    container: Container
    messaging: MessagingRuntime
    control_loop: ControlLoop
    readiness: StartupReadinessRuntime
    runtime_settings: RuntimeSettingsService
    discovery_activation: DiscoveryActivationRuntime | None
    semantic: SemanticRuntime
    pantheon: PantheonInitializationResult
    assignment_reconciliation_worker: AssignmentReconciliationWorker | None
    effect_reconciliation_worker: Any
    effect_reconciliation_request_binding: EffectReconciliationRequestRuntimeBinding | None
    operational_readiness_handler: OperationalReadinessEventHandler | None
    continuous_operating_model_worker: Any
    operating_intent_revalidation_worker: OperatingIntentSourceRevalidationWorker | None
    incident_creation_binding: bootstrap_incidents.IncidentCreationConsumerBinding
    incident_intervention_binding: bootstrap_incidents.IncidentInterventionConsumerBinding
    incident_notification_replay_worker: bootstrap_incidents.IncidentNotificationReplayWorker
    notification_receipt_applier: NotificationDeliveryReceiptApplier
    environment: Mapping[str, str]
    diagnostic_event_ingest_bridge: DiagnosticEventIngestBridge | None = None
    hil_workflow_registry: HilWorkflowDecisionRegistry | None = None
    stewardship_governance_worker: StewardshipGovernanceWorker | None = None
    stewardship_identity_health_worker: StewardshipIdentityHealthWorker | None = None
    stewardship_merge_effects_worker: StewardshipMergeEffectsWorker | None = None
    handover_knowledge_lifecycle_worker: HandoverKnowledgeLifecycleWorker | None = None
    assignment_intake_consumer: Any = None
    rule_activation_consumer: Any = None
    rule_activation_reconciliation: RuleActivationRuntimeReconciler | None = None
    assignment_outcome_consumer: Any = None
    human_access_reconciliation: Any = None
    task_workers: TaskWorkerRuntimeBinding | None = None
    assurance_twin_publishers: tuple[Any, ...] = ()
    assurance_twin_writers: tuple[Any, ...] = ()
    entitlement_state_publisher: Any = None

    def task_configuration(self, stop: asyncio.Event) -> RuntimeTaskConfiguration:
        """Project assembled bindings into the task-supervision contract."""

        return RuntimeTaskConfiguration(
            container=self.container,
            bus=self.messaging.bus,
            operational_bus=self.messaging.operational_bus,
            control_loop=self.control_loop,
            readiness=self.readiness,
            stop=stop,
            runtime_settings=self.runtime_settings,
            discovery_activation=self.discovery_activation,
            semantic_turn_binding=self.semantic.semantic_turn_binding,
            ontology_index_runtime=self.semantic.ontology_index_runtime,
            t1_mini_probe=self.semantic.t1_mini_probe,
            alert_noise_handler=self.pantheon.alert_noise_handler,
            divergence_ledger=self.pantheon.divergence_ledger,
            pantheon_runtime=self.pantheon.runtime,
            pantheon_heartbeat=self.pantheon.heartbeat,
            agent_introspection_server=self.pantheon.agent_introspection_server,
            runtime_state_publisher=self.pantheon.runtime_state_publisher,
            t2_recovery_maintenance=self.pantheon.t2_recovery_maintenance,
            assignment_reconciliation_worker=self.assignment_reconciliation_worker,
            effect_reconciliation_worker=self.effect_reconciliation_worker,
            effect_reconciliation_request_binding=self.effect_reconciliation_request_binding,
            continuous_operating_model_worker=self.continuous_operating_model_worker,
            operating_intent_revalidation_worker=self.operating_intent_revalidation_worker,
            rule_generation_binding=self.semantic.rule_generation_binding,
            rule_generation_reconciliation=self.semantic.rule_generation_reconciliation,
            case_history_retention_publisher=self.pantheon.case_history_retention_publisher,
            environment=self.environment,
            read_investigation_binding=self.semantic.read_investigation_binding,
            operational_readiness_handler=self.operational_readiness_handler,
            incident_creation_binding=self.incident_creation_binding,
            incident_intervention_binding=self.incident_intervention_binding,
            incident_notification_replay_worker=self.incident_notification_replay_worker,
            notification_receipt_applier=self.notification_receipt_applier,
            diagnostic_event_ingest_bridge=self.diagnostic_event_ingest_bridge,
            hil_workflow_registry=self.hil_workflow_registry,
            stewardship_governance_worker=self.stewardship_governance_worker,
            stewardship_identity_health_worker=self.stewardship_identity_health_worker,
            stewardship_merge_effects_worker=self.stewardship_merge_effects_worker,
            handover_knowledge_lifecycle_worker=self.handover_knowledge_lifecycle_worker,
            assignment_intake_consumer=self.assignment_intake_consumer,
            rule_activation_consumer=self.rule_activation_consumer,
            rule_activation_reconciliation=self.rule_activation_reconciliation,
            post_turn_review_request_consumer=self.pantheon.post_turn_review_request_consumer,
            assignment_outcome_consumer=self.assignment_outcome_consumer,
            human_access_reconciliation=self.human_access_reconciliation,
            assurance_twin_publishers=self.assurance_twin_publishers,
            assurance_twin_writers=self.assurance_twin_writers,
            entitlement_state_publisher=self.entitlement_state_publisher,
        )


def build_assurance_twin_runtime_binding(
    *,
    state_store: StateStore | None,
    agents: Collection[str] | None,
    event_bus: EventBus,
    retained_source: RetainedTwinEvidenceSource | None,
    posture_evaluator: CompletePostureEvaluator | None = None,
    inventory_dsn: str | None = None,
    posture_scope: str | None = None,
    required_inventory_scopes: tuple[str, ...] = (),
    reviewed_effects: tuple[ReviewedActionTypeEffect, ...] = (),
) -> tuple[tuple[Any, ...], tuple[AssuranceTwinAgentWriter, ...]]:
    """Bind no writer without the durable store and all three accountable agents.

    With production Inventory and T0/OPA inputs, Heimdall's posture producer and
    Forseti's typed-proposal review producer share the retained Inventory source.
    Forseti reviews only ActionType versions in ``reviewed_effects``; an empty
    catalog keeps every submitted proposal explicitly unavailable.
    """

    if (
        state_store is None
        or agents is None
        or not {"Heimdall", "Forseti", "Saga"}.issubset(agents)
    ):
        return (), ()

    ledger = StateStoreAssuranceTwinPostureLedger(store=state_store)
    publishers: tuple[Any, ...] = tuple(
        AssuranceTwinOutboxPublisher(owner=owner, ledger=ledger, bus=event_bus)
        for owner in ("Heimdall", "Forseti")
    )
    posture_inventory_fence: AssuranceTwinPostureProducer | None = None
    review_inventory_fence: AssuranceTwinReviewProducer | None = None
    if retained_source is None:
        repository = StateStoreTwinEvidenceRepository(store=state_store)
        retained_source = repository
        posture_producers: tuple[Any, ...] = ()
        if (
            posture_evaluator is not None
            and inventory_dsn is not None
            and inventory_dsn.strip()
            and posture_scope is not None
            and posture_scope.strip()
            and required_inventory_scopes
        ):
            inventory_source = PostgresTwinInventorySource(
                config=PostgresInventorySnapshotStoreConfig(dsn=inventory_dsn)
            )
            posture_inventory_fence = AssuranceTwinPostureProducer(
                inventory=inventory_source,
                evaluator=posture_evaluator,
                repository=repository,
                scope=posture_scope,
                required_scopes=required_inventory_scopes,
            )
            review_inventory_fence = AssuranceTwinReviewProducer(
                inventory=inventory_source,
                evaluator=posture_evaluator,
                repository=repository,
                intake=StateStoreTypedProposalReviewIntake(store=state_store),
                effects=ReviewedEffectCatalog(reviewed_effects),
                required_scopes=required_inventory_scopes,
            )
            posture_producers = (posture_inventory_fence, review_inventory_fence)
        publishers = (
            *posture_producers,
            AssuranceTwinEvidenceRequestRelay(
                repository=repository,
                bus=event_bus,
            ),
            *publishers,
        )

    recorder = AssuranceTwinPostureRecorder(ledger=ledger)
    owners: tuple[Literal["Heimdall", "Forseti"], ...] = ("Heimdall", "Forseti")
    writers = tuple(
        AssuranceTwinAgentWriter(
            owner=owner,
            source=retained_source,
            recorder=recorder,
            posture_generation_fence=(posture_evaluator if owner == "Heimdall" else None),
            posture_inventory_fence=(posture_inventory_fence if owner == "Heimdall" else None),
            review_generation_fence=(
                posture_evaluator if review_inventory_fence is not None else None
            ),
            review_inventory_fence=review_inventory_fence,
        )
        for owner in owners
    )
    return publishers, writers


def assurance_twin_inventory_dsn(environment: Mapping[str, str]) -> str | None:
    """Prefer the configured Inventory database over the shared state database."""

    return (
        environment.get("FDAI_INVENTORY_DSN", "").strip()
        or environment.get("FDAI_STATE_STORE_DSN", "").strip()
        or None
    )


__all__ = ["CoreRuntime", "assurance_twin_inventory_dsn"]
