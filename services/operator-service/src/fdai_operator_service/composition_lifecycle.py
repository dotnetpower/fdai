"""Application lifecycle ownership for the independent Operator service."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from fdai_operator_service.adapters import (
    LiveStageKafkaRelay,
    OperatorSemanticKafkaBus,
    StartupOwnedLocalAzureNarratorAdapters,
)
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)
from fdai_operator_service.assessment_projections import (
    FrameworkAssessmentProjectionBridge,
    WaraAssessmentProjectionBridge,
)
from fdai_operator_service.azure_monitor_webhook_runtime import AzureMonitorWebhookBridge
from fdai_operator_service.background_task_projection_runtime import (
    BackgroundTaskProjectionBridge,
)
from fdai_operator_service.contracts import ApplicationLifecycle
from fdai_operator_service.families.conversation.semantic_turn_runtime import SemanticTurnBridge
from fdai_operator_service.iam_composition import AssignmentNoticeBridge, HilDecisionOutboxBridge
from fdai_operator_service.model_lifecycle_composition import OperatorResolvedModelsRevisionOwner
from fdai_operator_service.observer_deployment_projection import ObserverProposalBridge
from fdai_operator_service.outbox_runtime import (
    ActionConfirmationBridge,
    AlertQualityBridge,
    IncidentInterventionBridge,
    TestContextBridge,
)
from fdai_operator_service.read_investigation_completion_runtime import (
    ReadInvestigationCompletionBridge,
)
from fdai_operator_service.read_investigation_runtime import ReadInvestigationBridge


class OwnedHttpClient:
    """Close one composition-owned HTTP client with the application lifecycle."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def start(self) -> None:
        """Own no startup work; the client is ready when it is constructed."""

    async def aclose(self) -> None:
        """Close the owned client exactly once."""
        if not self._client.is_closed:
            await self._client.aclose()


@dataclass(frozen=True, slots=True)
class CompositeLifecycle:
    """Start owned services in order and close them in reverse order."""

    services: tuple[ApplicationLifecycle, ...]

    async def start(self) -> None:
        """Start dependencies in order and close every acquired resource on failure."""
        started: list[ApplicationLifecycle] = []
        for service in self.services:
            try:
                await service.start()
            except BaseException as start_error:
                cleanup_errors: list[BaseException] = []
                for acquired in (service, *reversed(started)):
                    try:
                        await acquired.aclose()
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                if cleanup_errors:
                    raise BaseExceptionGroup(
                        "Operator startup and cleanup failed",
                        [start_error, *cleanup_errors],
                    ) from None
                raise
            started.append(service)

    async def aclose(self) -> None:
        """Close dependencies in reverse order so bridge consumers stop before Kafka."""
        first_error: BaseException | None = None
        for service in reversed(self.services):
            try:
                await service.aclose()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def compose_application_lifecycle(
    *services: ApplicationLifecycle | None,
) -> ApplicationLifecycle | None:
    """Combine application lifecycles while preserving startup and shutdown order."""
    active_services = tuple(service for service in services if service is not None)
    if not active_services:
        return None
    if len(active_services) == 1:
        return active_services[0]
    return CompositeLifecycle(active_services)


def application_lifecycle(
    model_revision_owner: OperatorResolvedModelsRevisionOwner | None,
    local_narrator: StartupOwnedLocalAzureNarratorAdapters | None,
    bridge: SemanticTurnBridge | None,
    read_investigation_bridge: ReadInvestigationBridge | None,
    background_task_projection_bridge: BackgroundTaskProjectionBridge | None,
    wara_assessment_projection_bridge: WaraAssessmentProjectionBridge | None,
    framework_assessment_projection_bridge: FrameworkAssessmentProjectionBridge | None,
    read_investigation_completion_bridge: ReadInvestigationCompletionBridge | None,
    action_confirmation_bridge: ActionConfirmationBridge | None,
    incident_intervention_bridge: IncidentInterventionBridge | None,
    azure_monitor_webhook_bridge: AzureMonitorWebhookBridge | None,
    live_activity_snapshot_loader: ApplicationLifecycle | None,
    bus: OperatorSemanticKafkaBus | None,
    live_stage_relay: LiveStageKafkaRelay | None,
    narrator_scheduler: PeriodicNarratorRefreshScheduler | None,
    hil_decision_outbox_bridge: HilDecisionOutboxBridge | None,
    teams_http_client: httpx.AsyncClient | None,
    assignment_notice_bridge: AssignmentNoticeBridge | None = None,
    alert_quality_bridge: AlertQualityBridge | None = None,
    test_context_bridge: TestContextBridge | None = None,
    observer_proposal_bridge: ObserverProposalBridge | None = None,
) -> ApplicationLifecycle | None:
    """Compose every process-owned lifecycle in dependency order."""
    return compose_application_lifecycle(
        model_revision_owner,
        local_narrator,
        bus,
        bridge,
        read_investigation_bridge,
        background_task_projection_bridge,
        wara_assessment_projection_bridge,
        framework_assessment_projection_bridge,
        read_investigation_completion_bridge,
        action_confirmation_bridge,
        incident_intervention_bridge,
        azure_monitor_webhook_bridge,
        alert_quality_bridge,
        live_activity_snapshot_loader,
        live_stage_relay,
        narrator_scheduler,
        hil_decision_outbox_bridge,
        test_context_bridge,
        assignment_notice_bridge,
        observer_proposal_bridge,
        OwnedHttpClient(teams_http_client) if teams_http_client is not None else None,
    )


__all__ = [
    "CompositeLifecycle",
    "OwnedHttpClient",
    "application_lifecycle",
    "compose_application_lifecycle",
]
