"""Compose governed document intent only from current PostgreSQL and identity owners."""

from __future__ import annotations

from fdai.agents import PantheonRuntime
from fdai.core.control_loop import ControlLoop
from fdai.delivery.document_intent_ingress import DocumentIntentIngress
from fdai.delivery.persistence.postgres_ontology import PostgresOntologyInstanceStore
from fdai.runtime.assignment_transport import AssignmentTransportRuntime
from fdai.runtime.document_intent import DocumentIntentRuntime, build_document_intent_runtime


def build_document_intent_binding(
    control_loop: ControlLoop,
    assignment: AssignmentTransportRuntime | None,
) -> DocumentIntentRuntime | None:
    if (
        assignment is None
        or assignment.core_handover is None
        or not isinstance(control_loop.ontology_instance_store, PostgresOntologyInstanceStore)
    ):
        return None
    return build_document_intent_runtime(
        graph=control_loop.ontology_instance_store,
        identities=assignment.core_handover.identities,
    )


def bind_document_intent_ingress(
    intent: DocumentIntentRuntime | None,
    runtime: PantheonRuntime,
) -> DocumentIntentIngress | None:
    return DocumentIntentIngress(intent, runtime.bridge) if intent is not None else None


__all__ = ["bind_document_intent_ingress", "build_document_intent_binding"]
