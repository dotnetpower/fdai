"""Catalog loading and authoritative control-loop assembly."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import yaml

from fdai.composition import (
    Container,
)
from fdai.core.architecture_review import (
    ArchitectureReviewProductionGateEvaluator,
    ArchitectureReviewProjector,
)
from fdai.core.chaos.symptom_index import SymptomIndex, build_from_promoted
from fdai.core.control_loop import ControlLoop
from fdai.core.event_ingest import EventCorrelator, EventIngest
from fdai.core.executor import ShadowExecutor
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.renderer import TemplateRenderer
from fdai.core.executor.tool_call import ToolReceiptObserver
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.quality_gate import (
    HashedRuleEmbeddingIndex,
    QualityGate,
    RagGroundingSource,
    RuleBasedVerifier,
)
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rca import KnowledgeEvidenceGatherer, RcaCoordinator
from fdai.core.risk_gate import ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.tiers.t0_deterministic.opa_evaluator import (
    MissingOpaBinaryError,
    OpaRegoEvaluator,
)
from fdai.core.tiers.t1_lightweight.tier import T1Tier
from fdai.core.tiers.t2_reasoning import T2Tier
from fdai.core.trust_router import TrustRouter
from fdai.core.workflow import (
    ProcessOntologyProjector,
    ProjectingProcessRuntimeStore,
    WorkflowApprovalPlanner,
    WorkflowOrchestrator,
    WorkflowTriggerCoordinator,
    WorkflowTriggerIndex,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.runtime.configuration import _resolve_catalog_root, _resolve_policies_root
from fdai.runtime.delivery import (
    _build_direct_api_executor,
    _build_hil_channel,
    _build_publisher,
    _build_tool_executor,
)
from fdai.runtime.providers import (
    _build_audit_store,
    _build_idempotency_store,
    _build_inventory_age_provider,
    _build_inventory_context_provider,
    _build_ontology_instance_store,
    _build_pattern_library,
    _build_process_store,
    _build_resource_lock,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.resilience import StateStoreKillSwitch

_LOGGER = logging.getLogger("fdai.startup")


async def _pending_index_writer(store: Any, approval_id: str) -> None:
    """Bridge the core HIL coordinator to the durable pending projection."""
    from fdai.delivery.persistence.state_store_hil_registry import add_pending_approval

    await add_pending_approval(store, approval_id)


def _build_workflow_coordinator(
    *,
    catalog_root: Path,
    workflows: tuple[Any, ...],
    action_types_by_name: dict[str, Any],
    audit_store: Any,
    process_store: Any | None = None,
    ontology_store: Any | None = None,
) -> WorkflowTriggerCoordinator | None:
    """Assemble the shadow workflow coordinator, opt-in and fail-safe.

    Disabled unless ``FDAI_WORKFLOW_SHADOW`` is truthy AND the catalog ships at
    least one Workflow. Any load error (missing / malformed rbac-groups or
    notifications matrix) logs and returns ``None`` so workflow wiring never
    fails boot or perturbs the control loop; upstream default is off.
    """
    if not workflows:
        return None
    if os.environ.get("FDAI_WORKFLOW_SHADOW", "").lower() not in ("1", "true", "yes", "on"):
        return None
    config_dir = catalog_root.parent / "config"
    rbac_file = config_dir / "rbac-groups.yaml"
    matrix_file = config_dir / "notifications-matrix.yaml"
    try:
        with rbac_file.open("r", encoding="utf-8") as fh:
            group_mapping = GroupMapping.from_config(yaml.safe_load(fh))
        matrix = load_matrix_from_yaml(matrix_file)
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
        review_manifest = catalog_root.parent / "config" / "architecture-review.yaml"
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
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=action_types_by_name,
        audit_store=audit_store,
        process_store=runtime_store,
        guard_evaluator=ArchitectureReviewProductionGateEvaluator(
            manifest_path=catalog_root.parent / "config" / "architecture-review.yaml",
            repo_root=catalog_root.parent,
        ),
    )
    _LOGGER.info("workflow_coordinator_enabled", extra={"workflows": len(workflows)})
    return WorkflowTriggerCoordinator(
        index=WorkflowTriggerIndex.build(workflows),
        orchestrator=orchestrator,
    )


def _load_resource_types() -> ResourceTypeRegistry:
    vocabulary_file = _resolve_catalog_root() / "vocabulary" / "resource-types.yaml"
    with vocabulary_file.open("r", encoding="utf-8") as handle:
        return load_resource_type_registry_from_mapping(yaml.safe_load(handle))


def _build_control_loop(
    container: Container,
    *,
    http_client: httpx.AsyncClient | None = None,
    stage_publisher: StagePublisher | None = None,
    audit_store: Any | None = None,
    tool_receipt_observer: ToolReceiptObserver | None = None,
    symptom_index: SymptomIndex | None = None,
) -> ControlLoop:
    """Load rule / action / policy catalogs and wire the P1 control loop.

    ``http_client`` - passed to :func:`_build_publisher` when the
    GitOps env vars opt into the real adapter. ``None`` is fine when
    the container runs in fake-publisher mode (dev / unit tests).
    """
    catalog_root = _resolve_catalog_root()
    policies_root = _resolve_policies_root(catalog_root)
    action_types_root = catalog_root / "action-types"
    object_types_root = catalog_root / "vocabulary" / "object-types"
    link_types_root = catalog_root / "vocabulary" / "link-types"
    remediation_root = catalog_root / "remediation"
    rules_root = catalog_root / "catalog"

    registry = container.schema_registry
    probes_root = catalog_root / "probes"
    action_types = load_action_type_catalog(
        action_types_root,
        schema_registry=registry,
        probes_root=probes_root if probes_root.is_dir() else None,
    )
    resource_types = _load_resource_types()

    # Ontology ObjectType / LinkType catalogs (fail-closed if directories
    # exist but any file is invalid). Missing directories are tolerated
    # so unit tests running against a stub catalog root do not require
    # every fixture to ship the vocabulary tree.
    ontology_object_types = (
        load_object_type_catalog(object_types_root, schema_registry=registry)
        if object_types_root.is_dir()
        else ()
    )
    ontology_link_types = (
        load_link_type_catalog(
            link_types_root,
            schema_registry=registry,
            object_types=ontology_object_types,
        )
        if link_types_root.is_dir() and ontology_object_types
        else ()
    )
    if ontology_object_types or ontology_link_types:
        container = replace(
            container,
            ontology_object_types=ontology_object_types,
            ontology_link_types=ontology_link_types,
        )

    rules = load_rule_catalog(
        rules_root,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    index = RuleIndex.build(rules)
    governance_catalog = load_governance_catalog(catalog_root)

    # Workflow catalog (fail-closed if the directory exists but any file is
    # invalid). Cross-references every step's action_type_ref / compensated_by
    # against the ActionType catalog and every guard_rule_ref against the rule
    # catalog, so a malformed workflow blocks boot rather than surfacing at
    # first dispatch (docs/roadmap/decisioning/process-automation.md 7).
    workflows_root = catalog_root / "workflows"
    workflows = (
        load_workflow_catalog(
            workflows_root,
            schema_registry=registry,
            action_type_names={a.name for a in action_types},
            rule_ids={r.id for r in rules},
        )
        if workflows_root.is_dir()
        else ()
    )
    if workflows:
        container = replace(container, workflows=workflows)

    try:
        evaluator: Any = OpaRegoEvaluator(policies_root=policies_root)
    except MissingOpaBinaryError as exc:
        # opa binary is required for full T0 verdicts; without it, T0
        # abstains on every candidate. Local dev keeps that fail-closed
        # fallback, but a deployed runtime must not advertise a healthy
        # deterministic tier that cannot evaluate any policy.
        runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
        if runtime_env in {"staging", "prod"}:
            raise RuntimeError(
                f"RUNTIME_ENV={runtime_env!r} requires the OPA binary for T0 policy evaluation"
            ) from exc
        _LOGGER.warning("opa_binary_missing_fallback_to_abstain")
        evaluator = None

    t0 = T0Engine(index=index, evaluator=evaluator)
    trust_router = TrustRouter(index=index)
    event_ingest = EventIngest(validator=container.event_validator)
    action_types_by_name = {a.name: a for a in action_types}
    action_builder = ActionBuilder(action_types_by_name=action_types_by_name)

    audit_store = audit_store or _build_audit_store()
    publisher = _build_publisher(http_client)
    renderer = TemplateRenderer(remediation_root=remediation_root)
    resource_lock = _build_resource_lock()
    idempotency_store = _build_idempotency_store()
    risk_table = load_risk_table(catalog_root / "risk-classification.yaml")
    promotion_registry: ActionPromotionRegistry
    promotion_state_refresher = None
    if os.environ.get("FDAI_STATE_STORE_DSN", "").strip():
        from fdai.delivery.persistence import StateStoreActionPromotionRegistry

        durable_registry = StateStoreActionPromotionRegistry(store=audit_store)
        promotion_registry = durable_registry
        promotion_state_refresher = durable_registry.refresh
    else:
        promotion_registry = ActionPromotionRegistry()
    risk_gate = RiskGate(
        registry=promotion_registry,
        exemption_registry=container.exemption_registry,
    )
    llm_bindings = container.require_llm_bindings()
    t1 = T1Tier(
        embedding_model=llm_bindings.embedding_model,
        pattern_library=_build_pattern_library(),
    )
    rules_by_id = {rule.id: rule for rule in rules}
    quality_gate = QualityGate(
        verifier=RuleBasedVerifier(rules_by_id=rules_by_id),
        cross_check_models=llm_bindings.cross_check_models,
        grounding=RagGroundingSource(
            rules=rules_by_id,
            embedding_index=HashedRuleEmbeddingIndex(),
        ),
        rubric_evaluator=llm_bindings.rubric_evaluator,
    )
    t2 = T2Tier(
        proposer=llm_bindings.require_t2_proposer(),
        quality_gate=quality_gate,
    )

    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_store,
        renderer=renderer,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
    )
    direct_api_executor = _build_direct_api_executor(
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
    )
    tool_executor = _build_tool_executor(
        audit_store=audit_store,
        resource_lock=resource_lock,
        idempotency=idempotency_store,
        receipt_observer=tool_receipt_observer,
        http_client=http_client,
        metric_provider=container.metric_provider,
    )

    # Detection-and-explanation seams (observability-and-detection.md).
    # EventCorrelator groups an event storm into one incident id; the
    # RcaCoordinator adds the deterministic T0 "why" per finding and,
    # when the Azure T2 RCA reasoner is bound (``t2.rca`` capability +
    # prompt), a grounded T2 hypothesis on novel (T0 no-match) cases.
    # Both are read-only explanation surfaces - never a new autonomy
    # path - so they are safe to wire unconditionally.
    event_correlator = EventCorrelator()
    rca_reasoner = (
        container.llm_bindings.rca_reasoner if container.llm_bindings is not None else None
    )
    # Free-form knowledge grounding leg: wrap the container's bound
    # KnowledgeSource (upstream default EmptyKnowledgeSource -> contributes
    # nothing) so a fork that ingests operator documents (runbooks,
    # resource plans) has them cited on T2 RCA. Safe to wire
    # unconditionally: an empty source yields no citations and the
    # grounding gate abstains rather than fabricating.
    rca_coordinator = RcaCoordinator(
        reasoner=rca_reasoner,
        symptom_index=symptom_index if symptom_index is not None else build_from_promoted(),
        knowledge_gatherer=KnowledgeEvidenceGatherer(source=container.knowledge_source),
    )

    # T1 temporal causal-chain RCA (observability-and-detection.md 4, path
    # b) needs the incident's antecedent changes, which upstream cannot
    # supply without wiring an estate-change source. It is therefore left
    # dark here: the loop keeps ``incident_member_source=None`` so only T0
    # (and, when bound, T2) RCA runs. A fork enables the multi-hop "root
    # change -> ... -> failure" chain by wiring the reference
    # ``DeploymentHistoryMemberSource`` (bridging a real
    # ``DeploymentHistoryProvider`` such as the Azure Resource Graph
    # adapter + ``IncidentRegistry.get`` lookup into ``CorrelatedEvent``s),
    # plus a ``causal_chain_window`` and optional
    # ``resource_dependency_graph``, into the ``ControlLoop`` here.

    # HIL approval round-trip (Notify-on-decision step B). Opt-in: only
    # when a HIL channel is configured (``FDAI_CHATOPS_WEBHOOK_URL``)
    # does the loop park a HIL-routed action and push an A1 approval
    # card. Absent -> ``None`` so the loop records the HIL verdict and
    # stops at the persisted queue (backward-compatible). Parking never
    # turns a HIL verdict into an execution - the coordinator holds the
    # no-self-approval + idempotency invariants.
    hil_channel = _build_hil_channel(http_client)
    hil_resume_coordinator = HilResumeCoordinator(
        state_store=audit_store,
        executor=executor,
        hil_channel=hil_channel,
        rules_by_id={r.id: r for r in rules},
        direct_api_executor=direct_api_executor,
        tool_executor=tool_executor,
        action_types_by_name=action_types_by_name,
        pending_index_writer=_pending_index_writer,
    )
    kill_switch = StateStoreKillSwitch(store=audit_store)

    return ControlLoop(
        event_ingest=event_ingest,
        trust_router=trust_router,
        t0_engine=t0,
        action_builder=action_builder,
        executor=executor,
        audit_store=audit_store,
        rules_by_id=rules_by_id,
        risk_table=risk_table,
        action_types_by_name=action_types_by_name,
        risk_gate=risk_gate,
        t1_engine=t1,
        t2_engine=t2,
        direct_api_executor=direct_api_executor,
        tool_executor=tool_executor,
        event_correlator=event_correlator,
        rca_coordinator=rca_coordinator,
        hil_resume_coordinator=hil_resume_coordinator,
        workflow_coordinator=_build_workflow_coordinator(
            catalog_root=catalog_root,
            workflows=workflows,
            action_types_by_name=action_types_by_name,
            audit_store=audit_store,
            process_store=_build_process_store(),
            ontology_store=(
                _build_ontology_instance_store(
                    object_types=ontology_object_types,
                    link_types=ontology_link_types,
                )
                if ontology_object_types and ontology_link_types
                else None
            ),
        ),
        governance_assignments=governance_catalog.assignments,
        inventory_age_provider=_build_inventory_age_provider(),
        inventory_context_provider=_build_inventory_context_provider(),
        promotion_state_refresher=promotion_state_refresher,
        stage_publisher=stage_publisher,
        kill_switch=kill_switch,
        kill_switch_refresher=kill_switch.refresh,
    )


def _build_irp_event_handler(*, container: Container, bus: EventBus) -> Any | None:
    """Build the alert-to-investigation bridge when explicitly enabled."""
    if os.environ.get("FDAI_IRP_ENABLED", "").strip() != "1":
        return None
    budget_raw = os.environ.get("FDAI_IRP_BUDGET_SECONDS", "").strip()
    try:
        budget_seconds = float(budget_raw) if budget_raw else 60.0
    except ValueError as exc:
        raise RuntimeError("FDAI_IRP_BUDGET_SECONDS MUST be a number") from exc
    from fdai.core.investigation import InvestigationCoordinator, default_analyzers
    from fdai.core.irp import IrpCoordinator
    from fdai.delivery.irp import EventBusIrpProposalRouter, IrpEventHandler

    signal_writer = None
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresReportSignalStore,
            PostgresReportSignalStoreConfig,
        )

        signal_writer = PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn))
    coordinator = IrpCoordinator(
        investigator=InvestigationCoordinator(
            analyzers=default_analyzers(container.metric_provider)
        ),
        proposal_router=EventBusIrpProposalRouter(
            bus=bus,
            topic=container.config.kafka.topic_events,
        ),
        investigation_budget_seconds=budget_seconds,
    )
    return IrpEventHandler(coordinator=coordinator, signal_writer=signal_writer)
