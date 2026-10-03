"""Aggregate Operator readiness across the durable store, bus, and owned workers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdai_operator_service.adapters import LiveStageKafkaRelay, OperatorSemanticKafkaBus
    from fdai_operator_service.assessment_projections import (
        FrameworkAssessmentProjectionBridge,
        WaraAssessmentProjectionBridge,
    )
    from fdai_operator_service.azure_monitor_webhook_runtime import AzureMonitorWebhookBridge
    from fdai_operator_service.background_task_projection_runtime import (
        BackgroundTaskProjectionBridge,
    )
    from fdai_operator_service.contracts import ReadinessProbe
    from fdai_operator_service.families.conversation.semantic_turn_runtime import (
        SemanticTurnBridge,
    )
    from fdai_operator_service.iam_composition import (
        AssignmentNoticeBridge,
        HilDecisionOutboxBridge,
    )
    from fdai_operator_service.observer_deployment_projection import ObserverProposalBridge
    from fdai_operator_service.outbox_runtime import (
        ActionConfirmationBridge,
        AlertQualityBridge,
        IncidentInterventionBridge,
        TestContextBridge,
    )
    from fdai_operator_service.postgres_family_store import PostgresFamilyStore
    from fdai_operator_service.read_investigation_completion_runtime import (
        ReadInvestigationCompletionBridge,
    )
    from fdai_operator_service.read_investigation_runtime import ReadInvestigationBridge
    from fdai_operator_service.rule_activation_outbox import RuleActivationNoticeBridge


def readiness_probe(
    store: PostgresFamilyStore | None,
    bus: OperatorSemanticKafkaBus | None,
    bridge: SemanticTurnBridge | None,
    read_investigation_bridge: ReadInvestigationBridge | None,
    background_task_projection_bridge: BackgroundTaskProjectionBridge | None,
    wara_assessment_projection_bridge: WaraAssessmentProjectionBridge | None,
    framework_assessment_projection_bridge: FrameworkAssessmentProjectionBridge | None,
    read_investigation_completion_bridge: ReadInvestigationCompletionBridge | None,
    action_confirmation_bridge: ActionConfirmationBridge | None,
    incident_intervention_bridge: IncidentInterventionBridge | None,
    azure_monitor_webhook_bridge: AzureMonitorWebhookBridge | None,
    live_stage_relay: LiveStageKafkaRelay | None,
    hil_decision_outbox_bridge: HilDecisionOutboxBridge | None = None,
    assignment_notice_bridge: AssignmentNoticeBridge | None = None,
    rule_activation_notice_bridge: RuleActivationNoticeBridge | None = None,
    alert_quality_bridge: AlertQualityBridge | None = None,
    test_context_bridge: TestContextBridge | None = None,
    observer_proposal_bridge: ObserverProposalBridge | None = None,
    action_confirmation_required: bool = False,
) -> ReadinessProbe:
    if store is None:
        return unavailable_readiness
    if bus is None:
        return store.probe_readiness

    async def probe() -> bool:
        if action_confirmation_required and action_confirmation_bridge is None:
            return False
        return (
            await store.probe_readiness()
            and await bus.probe_readiness()
            and (bridge is None or bridge.workers_ready())
            and (read_investigation_bridge is None or read_investigation_bridge.workers_ready())
            and (
                background_task_projection_bridge is None
                or background_task_projection_bridge.workers_ready()
            )
            and (
                wara_assessment_projection_bridge is None
                or wara_assessment_projection_bridge.workers_ready()
            )
            and (
                framework_assessment_projection_bridge is None
                or framework_assessment_projection_bridge.workers_ready()
            )
            and (
                read_investigation_completion_bridge is None
                or read_investigation_completion_bridge.workers_ready()
            )
            and (action_confirmation_bridge is None or action_confirmation_bridge.workers_ready())
            and (
                incident_intervention_bridge is None or incident_intervention_bridge.workers_ready()
            )
            and (
                azure_monitor_webhook_bridge is None or azure_monitor_webhook_bridge.workers_ready()
            )
            and (live_stage_relay is None or live_stage_relay.readiness())
            and (hil_decision_outbox_bridge is None or hil_decision_outbox_bridge.workers_ready())
            and (alert_quality_bridge is None or alert_quality_bridge.workers_ready())
            and (test_context_bridge is None or test_context_bridge.workers_ready())
            and (assignment_notice_bridge is None or assignment_notice_bridge.workers_ready())
            and (
                rule_activation_notice_bridge is None
                or rule_activation_notice_bridge.workers_ready()
            )
            and (observer_proposal_bridge is None or observer_proposal_bridge.workers_ready())
        )

    return probe


async def unavailable_readiness() -> bool:
    return False


__all__ = ["readiness_probe", "unavailable_readiness"]
