"""Compose immutable receipt validation and the fixed-owner assignment workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path

import httpx
from fdai_core_service.assignment_intake_consumer import AssignmentIntakeConsumer

from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader
from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.core.human_assignment.knowledge_stage import HandoverKnowledgeStage
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.scoped_duty_requests import ScopedDutyRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.human_reporting import (
    ReportingLineRequestProcessor,
    ReportingLineService,
    StateStoreReportingLineDraftReader,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_assignment_receipts import PostgresAssignmentReceiptReader
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader
from fdai.delivery.persistence.postgres_handover_goals import PostgresHandoverGoalReader
from fdai.runtime.core_handover import (
    CoreHandoverServices,
    CurrentCoreHandoverSource,
    build_core_handover_services,
)
from fdai.runtime.scoped_duties import build_scoped_duty_processor
from fdai.shared.providers.handover_goals import HandoverGoalProjectionReader
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class AssignmentTransportRuntime:
    """A nonprivileged consumer and capability-separated agent bindings."""

    consumer: AssignmentIntakeConsumer
    workflow: AssignmentWorkflowBindings
    scoped: ScopedDutyRequestProcessor | None = None
    reporting: ReportingLineRequestProcessor | None = None
    core_handover: CoreHandoverServices | None = None

    def with_pantheon(self, pantheon: PantheonRuntime | None) -> AssignmentIntakeConsumer:
        """Use the public Huginn ingress only when the actual required agents are bound."""
        required = {"Huginn", "Forseti", "Var", "Saga", "Muninn"}
        if pantheon is None or not required.issubset(pantheon.agents):
            return self.consumer
        return dataclass_replace(self.consumer, ingress=pantheon.ingest_raw_event)


def build_assignment_transport(
    *,
    store: StateStore,
    environment: Mapping[str, str],
    catalog_root: Path | None = None,
    http_client: httpx.AsyncClient | None = None,
    identity: WorkloadIdentity | None = None,
) -> AssignmentTransportRuntime | None:
    """Bind same-venue read-only receipts; a missing DSN never falls back to memory."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return None
    intake = AssignmentRequestIntake(
        receipts=PostgresAssignmentReceiptReader(PostgresStateStoreConfig(dsn=dsn)), store=store
    )
    scoped = build_scoped_duty_processor(
        intake=intake,
        environment=environment,
        catalog_root=catalog_root,
        http_client=http_client,
        identity=identity,
    )
    reporting = ReportingLineRequestProcessor(
        intake=intake,
        cases=ReportingLineService(store),
        drafts=StateStoreReportingLineDraftReader(store),
    )
    processor = AssignmentRequestProcessor(
        intake=intake,
        cases=AssignmentCaseService(store),
        scoped=scoped,
        reporting=reporting,
    )
    core_handover = build_core_handover_services(
        store=store,
        environment=environment,
        catalog_root=catalog_root,
        http_client=http_client,
        identity=identity,
    )
    return AssignmentTransportRuntime(
        consumer=AssignmentIntakeConsumer(intake),
        scoped=scoped,
        reporting=reporting,
        core_handover=core_handover,
        workflow=AssignmentWorkflowBindings(
            validate=processor.validate,
            review=processor.validate_review,
            materializer=processor,
            iam_reader=AssignmentIamRequestReader(processor.cases).read,
            knowledge_stages=tuple(
                HandoverKnowledgeStage(
                    owner=owner,
                    store=store,
                    source=HandoverKnowledgeSourceCheck(
                        CurrentCoreHandoverSource(
                            PostgresHandoverSourceReader(PostgresStateStoreConfig(dsn=dsn)),
                            core_handover,
                        )
                    ),
                )
                for owner in ("Forseti", "Muninn", "Norns", "Mimir")
            ),
        ),
    )


def build_handover_goal_reader(
    environment: Mapping[str, str],
) -> HandoverGoalProjectionReader | None:
    """Bind only the explicit same-venue read projection, never a mutable workflow store."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    return PostgresHandoverGoalReader(PostgresStateStoreConfig(dsn=dsn)) if dsn else None


__all__ = ["AssignmentTransportRuntime", "build_assignment_transport", "build_handover_goal_reader"]
