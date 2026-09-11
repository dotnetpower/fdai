"""Workflow and HIL configuration support for control-loop assembly."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fdai.core.architecture_review import (
    ArchitectureReviewProductionGateEvaluator,
    ArchitectureReviewProjector,
    ProductionEvidenceProvider,
)
from fdai.core.hil_resume import (
    ApprovalLoadPolicy,
    EscalationDuty,
    EscalationRung,
)
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.operational_context import StateStoreOperatingIntentAdmissionReader
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.risk_gate import OntologyChangeWindowEvidenceProvider
from fdai.core.stewardship import (
    Duty,
    EscalationTier,
    build_escalation_plan,
    load_stewardship_from_yaml,
)
from fdai.core.workflow import (
    AdmittedWorkflowGuardEvaluator,
    ChangeWindowWorkflowGuardEvaluator,
    ProcessOntologyProjector,
    ProjectingProcessRuntimeStore,
    RecoveryCoordinatorConfig,
    StateStoreAutomationHoldLedger,
    StateStoreWorkflowOutcomeLedger,
    WorkflowApprovalPlanner,
    WorkflowContextualGuardEvaluator,
    WorkflowGuardEvaluator,
    WorkflowOrchestrator,
    WorkflowRecoveryCoordinator,
    WorkflowTriggerCoordinator,
    WorkflowTriggerIndex,
)
from fdai.core.workflow.recovery_effect_ingress import (
    DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS,
    DEFAULT_TRUSTED_RECOVERY_EFFECT_OBSERVER_IDENTITIES,
    RecoveryEffectObservationIngress,
)
from fdai.core.workflow.workflow_runtime import WorkflowActionDispatcher
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.delivery.persistence.workflow_recovery import (
    StateStoreRecoveryApprovalJournal,
    StateStoreRecoveryAttemptResolver,
    StateStoreRecoveryEffectObservationJournal,
    StateStoreRecoveryEffectObserver,
    StateStoreRecoverySafeguardBundleReader,
    StateStoreRecoverySafeguardBundleRetention,
    WorkflowActionRecoveryDispatchPort,
    WorkflowRecoveryOutcomeRecorder,
)
from fdai.runtime.operating_intent_binding import (
    operating_intent_admission_expectation_from_env,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

_LOGGER = logging.getLogger("fdai.startup")


def build_operating_intent_change_window_provider(
    ontology_store: Any,
    audit_store: Any,
) -> OntologyChangeWindowEvidenceProvider:
    """Bind change-window reads to the process's exact intent admission expectation."""

    return OntologyChangeWindowEvidenceProvider(
        ontology_store,
        intent_admission=StateStoreOperatingIntentAdmissionReader(
            audit_store,
            expectation=operating_intent_admission_expectation_from_env(os.environ),
        ),
    )


async def pending_index_writer(store: Any, approval_id: str) -> None:
    """Bridge the core HIL coordinator to the durable pending projection."""
    from fdai.delivery.persistence.state_store_hil_registry import add_pending_approval

    await add_pending_approval(store, approval_id)


def build_workflow_coordinator(
    *,
    catalog_root: Path,
    workflows: tuple[Any, ...],
    action_types_by_name: dict[str, Any],
    audit_store: Any,
    process_store: Any | None = None,
    ontology_store: Any | None = None,
    outcome_verifier: StateStoreWorkflowOutcomeLedger | None = None,
    architecture_evidence_provider: ProductionEvidenceProvider | None = None,
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None = None,
    action_dispatcher: WorkflowActionDispatcher | None = None,
) -> WorkflowTriggerCoordinator | None:
    """Assemble the default-on shadow workflow coordinator without widening authority."""
    if not workflows:
        return None
    if os.environ.get("FDAI_WORKFLOW_SHADOW", "").strip().casefold() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    config_dir = catalog_root.parent / "config"
    try:
        with (config_dir / "rbac-groups.yaml").open("r", encoding="utf-8") as handle:
            group_mapping = GroupMapping.from_config(yaml.safe_load(handle))
        matrix = load_matrix_from_yaml(config_dir / "notifications-matrix.yaml")
    except (OSError, ValueError) as exc:
        _LOGGER.warning("workflow_coordinator_disabled", extra={"error": type(exc).__name__})
        return None
    planner = WorkflowApprovalPlanner(
        action_types=action_types_by_name,
        group_mapping=group_mapping,
        matrix=matrix,
    )
    runtime_store = process_store or InMemoryProcessRuntimeStore()
    if ontology_store is not None:
        domain_projectors: dict[str, Any] = {}
        review_manifest = config_dir / "architecture-review.yaml"
        if review_manifest.is_file():
            with review_manifest.open("r", encoding="utf-8") as handle:
                raw_manifest = yaml.safe_load(handle)
            if not isinstance(raw_manifest, dict):
                raise ValueError("config/architecture-review.yaml MUST contain a mapping")
            domain_projectors["architecture-review"] = ArchitectureReviewProjector(
                ontology_store,
                raw_manifest,
            )
        runtime_store = ProjectingProcessRuntimeStore(
            runtime=runtime_store,
            projector=ProcessOntologyProjector(
                ontology_store,
                domain_projectors=domain_projectors,
            ),
        )
    architecture_guard = ArchitectureReviewProductionGateEvaluator(
        manifest_path=config_dir / "architecture-review.yaml",
        repo_root=catalog_root.parent,
        evidence_provider=architecture_evidence_provider,
    )
    inner_guard: WorkflowContextualGuardEvaluator | WorkflowGuardEvaluator = (
        ChangeWindowWorkflowGuardEvaluator(
            change_windows=build_operating_intent_change_window_provider(
                ontology_store,
                audit_store,
            ),
            fallback=architecture_guard,
        )
        if ontology_store is not None
        else architecture_guard
    )
    guard_evaluator = AdmittedWorkflowGuardEvaluator(
        inner=inner_guard,
        decision_evidence_provider=decision_evidence_provider,
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=action_types_by_name,
        audit_store=audit_store,
        process_store=runtime_store,
        guard_evaluator=guard_evaluator,
        action_dispatcher=action_dispatcher,
        approval_provider=StateStoreWorkflowApprovalProvider(audit_store),
        approval_decision_evidence_provider=decision_evidence_provider,
        outcome_verifier=outcome_verifier,
        recovery_coordinator=build_workflow_recovery_coordinator(
            audit_store=audit_store,
            process_store=runtime_store,
            action_dispatcher=action_dispatcher,
            decision_evidence_provider=decision_evidence_provider,
        ),
    )
    _LOGGER.info("workflow_coordinator_enabled", extra={"workflows": len(workflows)})
    return WorkflowTriggerCoordinator(
        index=WorkflowTriggerIndex.build(workflows),
        orchestrator=orchestrator,
    )


def build_workflow_recovery_coordinator(
    *,
    audit_store: Any,
    process_store: Any,
    action_dispatcher: WorkflowActionDispatcher | None,
    decision_evidence_provider: DecisionEvidenceAdmissionProvider | None,
    environ: Mapping[str, str] | None = None,
) -> WorkflowRecoveryCoordinator:
    """Compose the durable recovery path that closes an automation hold."""

    values = environ if environ is not None else os.environ
    raw_revision = values.get("FDAI_SOURCE_REVISION", "").strip()
    if raw_revision and not raw_revision.startswith("commit:"):
        raw_revision = f"commit:{raw_revision}"
    if not raw_revision:
        raw_revision = "commit:" + "0" * 40
    executor_identity = (
        values.get("FDAI_WORKFLOW_EXECUTOR_IDENTITY", "").strip() or "fdai.core.workflow.executor"
    )
    journal = StateStoreRecoveryApprovalJournal(
        approvals=StateStoreWorkflowApprovalProvider(audit_store),
        requester_principal=(
            values.get("FDAI_WORKFLOW_RECOVERY_REQUESTER", "").strip()
            or "fdai.core.workflow.recovery-requester"
        ),
    )
    return WorkflowRecoveryCoordinator(
        process_store=process_store,
        audit_store=audit_store,
        holds=StateStoreAutomationHoldLedger(audit_store),
        config=RecoveryCoordinatorConfig(
            executor_identity=executor_identity,
            source_revision=raw_revision,
        ),
        dispatcher=(
            WorkflowActionRecoveryDispatchPort(
                dispatcher=action_dispatcher,
                store=audit_store,
            )
            if action_dispatcher is not None
            else None
        ),
        effect_observer=StateStoreRecoveryEffectObserver(audit_store),
        effect_observations=build_workflow_recovery_effect_observation_journal(
            audit_store=audit_store,
            environ=values,
        ),
        approval_reader=journal,
        approval_requester=journal,
        admission_provider=decision_evidence_provider,
        bundle_reader=StateStoreRecoverySafeguardBundleReader(audit_store),
    )


def build_workflow_recovery_outcome_recorder(
    inner: Any,
    *,
    audit_store: Any,
) -> WorkflowRecoveryOutcomeRecorder:
    """Retain a finalized recovery bundle at the production outcome call site."""

    return WorkflowRecoveryOutcomeRecorder(
        inner=inner,
        store=audit_store,
        retention=StateStoreRecoverySafeguardBundleRetention(audit_store),
    )


def build_workflow_recovery_effect_observation_journal(
    *,
    audit_store: Any,
    environ: Mapping[str, str] | None = None,
) -> StateStoreRecoveryEffectObservationJournal:
    """Expose the independent post-effect observation intake for the runtime.

    An observer that is independent of the executor writes its authoritative
    observation here. The journal refuses executor-owned, provider-owned, and
    synthetic evidence, so persistence never manufactures effect verification.
    """

    values = environ if environ is not None else os.environ
    return StateStoreRecoveryEffectObservationJournal(
        store=audit_store,
        executor_identity=(
            values.get("FDAI_WORKFLOW_EXECUTOR_IDENTITY", "").strip()
            or "fdai.core.workflow.executor"
        ),
    )


def build_workflow_recovery_effect_observation_ingress(
    *,
    audit_store: Any,
    environ: Mapping[str, str] | None = None,
) -> RecoveryEffectObservationIngress:
    """Compose the versioned observer-path ingress for recovery effects.

    The authorized observer principals and the executor identity come from
    composition, never from an event, so a published payload cannot nominate
    the identity it is validated against.
    """

    values = environ if environ is not None else os.environ
    principals = frozenset(
        item.strip()
        for item in values.get("FDAI_WORKFLOW_RECOVERY_OBSERVER_PRINCIPALS", "").split(",")
        if item.strip()
    )
    trusted_observers = frozenset(
        item.strip()
        for item in values.get(
            "FDAI_WORKFLOW_RECOVERY_OBSERVER_IDENTITIES",
            "",
        ).split(",")
        if item.strip()
    )
    return RecoveryEffectObservationIngress(
        attempts=StateStoreRecoveryAttemptResolver(audit_store),
        journal=build_workflow_recovery_effect_observation_journal(
            audit_store=audit_store,
            environ=values,
        ),
        executor_identity=(
            values.get("FDAI_WORKFLOW_EXECUTOR_IDENTITY", "").strip()
            or "fdai.core.workflow.executor"
        ),
        authorized_principals=principals or DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS,
        trusted_observer_identities=(
            trusted_observers or DEFAULT_TRUSTED_RECOVERY_EFFECT_OBSERVER_IDENTITIES
        ),
    )


def load_approval_load_policy(catalog_root: Path) -> ApprovalLoadPolicy | None:
    """Load the optional bounded approval load policy."""
    configured = os.environ.get("FDAI_APPROVAL_LOAD_POLICY", "").strip()
    path = Path(configured) if configured else catalog_root.parent / "config" / "approval-load.yaml"
    if not path.is_file():
        if configured:
            raise ValueError("FDAI_APPROVAL_LOAD_POLICY does not reference a file")
        return None
    with path.open("r", encoding="utf-8") as handle:
        decoded = yaml.safe_load(handle)
    if not isinstance(decoded, Mapping):
        raise ValueError("approval load policy MUST be a YAML object")
    return ApprovalLoadPolicy.from_mapping(decoded)


def load_hil_escalation_rungs(catalog_root: Path) -> tuple[EscalationRung, ...]:
    """Map stewardship duties onto the HIL escalation contract."""
    stewardship = load_stewardship_from_yaml(
        catalog_root.parent / "config" / "agent-stewardship.yaml",
        environ=os.environ,
    )
    plan = build_escalation_plan(stewardship, "Var")
    duty_map = {
        Duty.PRIMARY: EscalationDuty.PRIMARY,
        Duty.BACKUP: EscalationDuty.BACKUP,
        Duty.ESCALATION: EscalationDuty.ESCALATION,
    }
    rungs: list[EscalationRung] = []
    for recipient in plan.recipients:
        if recipient.tier is EscalationTier.INFORMED:
            continue
        if recipient.tier is EscalationTier.MAINTAINER:
            duty = EscalationDuty.MAINTAINER
            minimum_role = "Owner"
        elif recipient.duty is not None:
            duty = duty_map[recipient.duty]
            minimum_role = "Approver"
        else:
            continue
        rungs.append(EscalationRung(recipient.id, duty, minimum_role))
    return tuple(rungs)


__all__ = [
    "build_workflow_coordinator",
    "build_workflow_recovery_coordinator",
    "build_workflow_recovery_effect_observation_ingress",
    "load_approval_load_policy",
    "load_hil_escalation_rungs",
    "pending_index_writer",
]
