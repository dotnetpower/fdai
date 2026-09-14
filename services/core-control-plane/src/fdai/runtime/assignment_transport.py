"""Compose immutable receipt validation and the fixed-owner assignment workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace

from fdai_core_service.assignment_intake_consumer import AssignmentIntakeConsumer

from fdai.agents import AssignmentWorkflowBindings, PantheonRuntime
from fdai.core.human_assignment.request_intake import AssignmentRequestIntake
from fdai.core.human_assignment.request_processor import AssignmentRequestProcessor
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_assignment_receipts import PostgresAssignmentReceiptReader
from fdai.delivery.persistence.postgres_handover_goals import PostgresHandoverGoalReader
from fdai.shared.providers.handover_goals import HandoverGoalProjectionReader
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class AssignmentTransportRuntime:
    """A nonprivileged consumer and capability-separated agent bindings."""

    consumer: AssignmentIntakeConsumer
    workflow: AssignmentWorkflowBindings

    def with_pantheon(self, pantheon: PantheonRuntime | None) -> AssignmentIntakeConsumer:
        """Use the public Huginn ingress only when the actual required agents are bound."""
        required = {"Huginn", "Forseti", "Var", "Saga", "Muninn"}
        if pantheon is None or not required.issubset(pantheon.agents):
            return self.consumer
        return dataclass_replace(self.consumer, ingress=pantheon.ingest_raw_event)


def build_assignment_transport(
    *, store: StateStore, environment: Mapping[str, str]
) -> AssignmentTransportRuntime | None:
    """Bind same-venue read-only receipts; a missing DSN never falls back to memory."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return None
    intake = AssignmentRequestIntake(
        receipts=PostgresAssignmentReceiptReader(PostgresStateStoreConfig(dsn=dsn)), store=store
    )
    processor = AssignmentRequestProcessor(intake=intake, cases=AssignmentCaseService(store))
    return AssignmentTransportRuntime(
        consumer=AssignmentIntakeConsumer(intake),
        workflow=AssignmentWorkflowBindings(
            validate=processor.validate, review=processor.validate_review, materializer=processor
        ),
    )


def build_handover_goal_reader(
    environment: Mapping[str, str],
) -> HandoverGoalProjectionReader | None:
    """Bind only the explicit same-venue read projection, never a mutable workflow store."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    return PostgresHandoverGoalReader(PostgresStateStoreConfig(dsn=dsn)) if dsn else None


__all__ = ["AssignmentTransportRuntime", "build_assignment_transport", "build_handover_goal_reader"]
