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
    StateStoreWorkflowOutcomeLedger,
    WorkflowApprovalPlanner,
    WorkflowContextualGuardEvaluator,
    WorkflowGuardEvaluator,
    WorkflowOrchestrator,
    WorkflowTriggerCoordinator,
    WorkflowTriggerIndex,
)
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore

_LOGGER = logging.getLogger("fdai.startup")


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
            change_windows=OntologyChangeWindowEvidenceProvider(ontology_store),
            fallback=architecture_guard,
        )
        if ontology_store is not None
        else architecture_guard
    )
    guard_evaluator = AdmittedWorkflowGuardEvaluator(inner=inner_guard)
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=action_types_by_name,
        audit_store=audit_store,
        process_store=runtime_store,
        guard_evaluator=guard_evaluator,
        approval_provider=StateStoreWorkflowApprovalProvider(audit_store),
        outcome_verifier=outcome_verifier,
    )
    _LOGGER.info("workflow_coordinator_enabled", extra={"workflows": len(workflows)})
    return WorkflowTriggerCoordinator(
        index=WorkflowTriggerIndex.build(workflows),
        orchestrator=orchestrator,
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
    "load_approval_load_policy",
    "load_hil_escalation_rungs",
    "pending_index_writer",
]
