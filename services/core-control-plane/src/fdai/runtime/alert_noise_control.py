"""Bind alert planning to the already composed canonical Workflow runtime.

No orchestrator, Process store, approval provider, dispatcher or recovery engine
is created here. The parent's existing runtime remains the only Process writer.
Missing optional configuration or source provenance leaves alert writes unbound.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from fdai.core.detection.alert_noise.execution import ALERT_ACTIONS
from fdai.core.detection.alert_noise.workflow import (
    ALERT_WORKFLOWS,
    AlertActionBinder,
    AlertWorkflowCoordinator,
)
from fdai.core.risk_gate import ActionPromotionRegistry
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.delivery.alert_noise_pr import StateStoreAlertPlanReader
from fdai.delivery.alert_noise_workflow import (
    MappedAlertRequesterReader,
    StateStoreAlertActionBinder,
    StateStoreAlertWorkflowPromotionReader,
)
from fdai.runtime.alert_noise_config import parse_alert_noise_config
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyTypeRef,
    Workflow,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessRuntimeStore
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class AlertWorkflowBindings:
    """Optional ControlLoop inputs; neither member supplies execution authority."""

    workflows: AlertWorkflowCoordinator | None = None
    binder: AlertActionBinder | None = None


def registered_alert_actions(release: OntologyRelease) -> Mapping[str, OntologyTypeRef]:
    """Resolve only alert ActionType members of the exact loaded ontology release."""
    return MappingProxyType(
        {
            item.name: release.type_ref(OntologyDeclarationKind.ACTION, item.name)
            for item in release.declarations
            if item.kind is OntologyDeclarationKind.ACTION and item.name in ALERT_ACTIONS
        }
    )


def build_alert_workflow_bindings(
    *,
    workflow_coordinator: WorkflowTriggerCoordinator | None,
    workflows: Sequence[Workflow],
    action_types_by_name: Mapping[str, OntologyActionType],
    ontology_release: OntologyRelease,
    process_store: ProcessRuntimeStore,
    audit_store: StateStore,
    promotion_registry: ActionPromotionRegistry,
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None,
    environment: Mapping[str, str] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AlertWorkflowBindings:
    """Reuse normal orchestration, current identities, promotion and independent DE.

    A complete alert opt-in with explicit source requires the canonical runtime
    and loaded alert declarations. It does not require optional writer providers:
    identity membership never supplies approval and missing promotion stays shadow.
    Explicit partial JSON configuration raises rather than masquerading as absence.
    """
    config = parse_alert_noise_config(os.environ if environment is None else environment)
    if config is None or config.source_revision is None:
        return AlertWorkflowBindings()
    if workflow_coordinator is None:
        raise RuntimeError("alert workflows require the canonical Workflow coordinator")
    catalog = {workflow.name: workflow for workflow in workflows}
    registered = registered_alert_actions(ontology_release)
    if (
        not ALERT_ACTIONS.issubset(registered)
        or not ALERT_ACTIONS.issubset(action_types_by_name)
        or any(name not in catalog for name, _step in ALERT_WORKFLOWS.values())
        or any(
            action_types_by_name[name].name != name
            or action_types_by_name[name].version != ref.version
            for name, ref in registered.items()
        )
    ):
        raise ValueError("alert workflow composition requires the exact complete alert catalog")
    coordinator = AlertWorkflowCoordinator(
        plans=StateStoreAlertPlanReader(store=audit_store),
        requesters=MappedAlertRequesterReader(subjects=config.requester_subjects),
        workflows=catalog,
        action_types=action_types_by_name,
        registry=promotion_registry,
        promotions=StateStoreAlertWorkflowPromotionReader(
            store=audit_store,
            admission_provider=decision_evidence_provider,
            source_revision=config.source_revision,
            clock=clock,
        ),
        orchestrator=workflow_coordinator.runtime,
        process_store=process_store,
        store=audit_store,
        source_revision=config.source_revision,
        clock=clock,
    )
    return AlertWorkflowBindings(
        workflows=coordinator,
        binder=StateStoreAlertActionBinder(
            workflows=coordinator,
            registered_actions=registered,
            store=audit_store,
            clock=clock,
        ),
    )


__all__ = ["AlertWorkflowBindings", "build_alert_workflow_bindings", "registered_alert_actions"]
