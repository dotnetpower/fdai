"""Synthetic graph and process-view assembly for local development."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import yaml

from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.risk_gate.blast_radius_simulator import InMemoryOntologyGraph, OntologyGraph
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel

_REPO_ROOT = Path(__file__).resolve().parents[6]


def _group_mapping_from_env() -> GroupMapping:
    from fdai.delivery.read_api.dev.local import _group_mapping_from_env as build

    return build()


def _build_blast_radius_graph() -> OntologyGraph:
    """Small synthetic graph so the console's simulator has something to render."""
    return InMemoryOntologyGraph(
        edges={
            ("sub-example", "contains"): ("rg-network", "rg-app", "rg-data"),
            ("rg-network", "contains"): ("vnet-hub",),
            ("vnet-hub", "contains"): ("snet-ingress", "snet-private"),
            ("snet-ingress", "contains"): ("agw-prod", "lb-internal"),
            ("snet-private", "contains"): ("fw-hub",),
            ("rg-app", "contains"): ("web-api", "event-worker", "scheduler", "aks-ops"),
            ("rg-data", "contains"): ("pg-prod", "redis-prod", "stprod"),
            ("web-api", "depends_on"): ("event-worker", "pg-prod", "redis-prod"),
            ("event-worker", "attached_to"): ("stprod",),
            ("aks-ops", "attached_to"): ("kv-prod",),
        },
        link_types=frozenset({"contains", "depends_on", "attached_to"}),
    )


def _build_scope_view() -> Any:
    """Synthetic effective-scope view for the dev harness console panel.

    Customer-agnostic: placeholder all-zero-GUID subscriptions and generic
    resource-group names only. Reuses :class:`ScopeBinding` / :class:`ScopeRef`
    so the console view composes the real scope schema, not a parallel model.
    """
    from fdai.delivery.read_api.routes.scope import StaticScopeSource, build_scope_view
    from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeRef

    org = "example-org"
    sub_prod = "00000000-0000-0000-0000-000000000001"
    sub_nonprod = "00000000-0000-0000-0000-000000000002"

    monitoring = ScopeBinding(
        includes=(
            ScopeRef(segments=(org, sub_prod)),
            ScopeRef(segments=(org, sub_nonprod)),
        ),
        excludes=(ScopeRef(segments=(org, sub_nonprod, "rg-sandbox")),),
    )
    action = ScopeBinding(
        includes=(ScopeRef(segments=(org, sub_prod, "rg-example-app")),),
        excludes=(ScopeRef(segments=(org, sub_prod, "rg-example-data")),),
    )
    view = build_scope_view(
        monitoring=monitoring,
        action=action,
        executor_resource_groups=("rg-example-app",),
        executor_note=(
            "Executor managed identity is RG-scoped and action-whitelisted; "
            "no governance scope can widen it."
        ),
    )
    return StaticScopeSource(view)


class _DemoTighterTagsEvaluator:
    """Toy :class:`WhatIfEvaluator` for the dev harness.

    Denies whenever the reconstructed event's props do not carry an
    ``owner`` tag, so a fork engineer can eyeball the what-if diff
    against the shipped rules that already deny on the same property.
    """

    def evaluate(
        self, resource_type: str, resource_props: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        del resource_type  # this scenario is type-agnostic
        tags = resource_props.get("tags") or {}
        if isinstance(tags, dict) and tags.get("owner"):
            return ()
        return (
            {
                "rule_id": "dev.tighter-tags.owner-required",
                "denied": True,
                "reason": "missing_owner_tag",
            },
        )


def _build_dynamic_process_views_sync(
    *,
    read_model: InMemoryConsoleReadModel,
    object_types: tuple[Any, ...],
    link_types: tuple[Any, ...],
    workflows: tuple[Any, ...],
    action_types: tuple[Any, ...],
) -> tuple[Any, Any, Any]:
    build = _build_dynamic_process_views(
        read_model=read_model,
        object_types=object_types,
        link_types=link_types,
        workflows=workflows,
        action_types=action_types,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(build)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="fdai-dev-seed") as executor:
        return executor.submit(asyncio.run, build).result()


async def _build_dynamic_process_views(
    *,
    read_model: InMemoryConsoleReadModel,
    object_types: tuple[Any, ...],
    link_types: tuple[Any, ...],
    workflows: tuple[Any, ...],
    action_types: tuple[Any, ...],
) -> tuple[Any, Any, Any]:
    """Seed one truthful dev Process and wire its declarative read projections."""
    from fdai.core.architecture_review import ArchitectureReviewProjector
    from fdai.core.reporting.composition import default_reporting_engine
    from fdai.core.reporting.datasources import AuditReader
    from fdai.core.views import ViewEngine, load_view_catalog, load_workflow_app_catalog
    from fdai.core.workflow.approval import WorkflowApprovalPlanner
    from fdai.core.workflow.orchestrator import WorkflowOrchestrator
    from fdai.core.workflow.projection import (
        ProcessOntologyProjector,
        ProjectingProcessRuntimeStore,
    )
    from fdai.delivery.read_api.dev.fixtures.security_assessment import (
        build_dev_security_assessment_feed,
    )
    from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
    from fdai.delivery.read_api.routes.reporting import ReportingConfig
    from fdai.delivery.read_api.routes.workflow_execution import WorkflowExecutionConfig
    from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
    from fdai.shared.providers.ontology_instance import OntologyObjectRecord
    from fdai.shared.providers.process_runtime import (
        ProcessEvent,
        ProcessEventKind,
        ProcessSnapshot,
        ProcessStatus,
    )
    from fdai.shared.providers.testing import (
        InMemoryOntologyInstanceStore,
        InMemoryProcessRuntimeStore,
        InMemoryStateStore,
    )

    ontology = InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=link_types,
    )
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="fdai-control-plane",
            object_type="Resource",
            properties={
                "id": "fdai-control-plane",
                "type": "control-plane",
                "name": "FDAI control plane",
            },
        )
    )
    manifest = yaml.safe_load(
        (_REPO_ROOT / "config" / "architecture-review.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(manifest, Mapping):
        raise ValueError("config/architecture-review.yaml MUST contain a mapping")
    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=ProcessOntologyProjector(
            ontology,
            domain_projectors={
                "architecture-review": ArchitectureReviewProjector(ontology, manifest)
            },
        ),
    )
    now = datetime.now(tz=UTC)
    process_id = "dev-architecture-review"
    correlation_id = "dev-architecture-review"
    snapshot, _ = await runtime.create(
        snapshot=ProcessSnapshot(
            process_id=process_id,
            workflow_ref="architecture-review",
            workflow_version="1.0.0",
            status=ProcessStatus.PENDING,
            current_step="",
            target_resource_id="fdai-control-plane",
            started_at=now,
            updated_at=now,
            correlation_id=correlation_id,
        ),
        event=ProcessEvent(
            event_id="dev-arb-created",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="dev-arb:created",
            recorded_at=now,
            correlation_id=correlation_id,
        ),
    )
    running = await runtime.transition(
        process_id=process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.RUNNING,
        current_step="domain_reviews",
        event=ProcessEvent(
            event_id="dev-arb-domain-reviews",
            process_id=process_id,
            kind=ProcessEventKind.STEP_COMPLETED,
            idempotency_key="dev-arb:domain-reviews",
            recorded_at=now,
            correlation_id=correlation_id,
            step_id="domain_reviews",
            payload={"branches": ["security", "privacy", "data", "reliability"]},
        ),
    )
    await runtime.transition(
        process_id=process_id,
        expected_revision=running.revision,
        status=ProcessStatus.WAITING,
        current_step="evidence",
        event=ProcessEvent(
            event_id="dev-arb-evidence-wait",
            process_id=process_id,
            kind=ProcessEventKind.STEP_WAITING,
            idempotency_key="dev-arb:evidence-wait",
            recorded_at=now,
            correlation_id=correlation_id,
            step_id="evidence",
        ),
    )
    metric_provider = StaticMetricProvider(
        tuple(
            MetricPoint(
                metric_name="fdai.audit.entries.count",
                at=now - timedelta(minutes=55 - index * 5),
                value=float(value),
                labels={"mode": mode, "actor": actor},
            )
            for index, (value, mode, actor) in enumerate(
                (
                    (2, "shadow", "Huginn"),
                    (3, "shadow", "Forseti"),
                    (4, "shadow", "Thor"),
                    (1, "enforce", "Saga"),
                    (5, "shadow", "Njord"),
                    (2, "enforce", "Var"),
                    (3, "shadow", "Muninn"),
                    (4, "shadow", "Norns"),
                    (1, "enforce", "Odin"),
                    (2, "shadow", "Freyr"),
                    (3, "shadow", "Vidar"),
                    (4, "shadow", "Heimdall"),
                )
            )
        )
    )
    report_engine, formats = default_reporting_engine(
        reports_root=_REPO_ROOT / "rule-catalog" / "reports",
        audit_reader=cast(AuditReader, read_model),
        report_feed=build_dev_security_assessment_feed(now),
        metric_provider=metric_provider,
        ontology_store=ontology,
        process_store=runtime,
    )
    from fdai.core.reporting.models import DataSourceProvenance

    for datasource in ("audit", "ontology", "report_feed", "security_assessment"):
        report_engine.datasource_registry().register(
            report_engine.datasource_registry().get(datasource),
            provenance=DataSourceProvenance(
                datasource=datasource,
                source="synthetic-dev",
                availability="available",
                synthetic=True,
                as_of=now.isoformat(),
            ),
        )
    report_engine.datasource_registry().register(
        report_engine.datasource_registry().get("metric"),
        provenance=DataSourceProvenance(
            datasource="metric",
            source="static-dev-metric",
            availability="available",
            synthetic=True,
            as_of=now.isoformat(),
        ),
    )
    from fdai.delivery.reporting import install_pdf_format_if_available

    install_pdf_format_if_available(formats)
    view_specs = load_view_catalog(
        _REPO_ROOT / "rule-catalog" / "views",
        report_ids={spec.id for spec in report_engine.catalog().list()},
        workflow_names={workflow.name for workflow in workflows},
    )
    workflow_apps = load_workflow_app_catalog(
        _REPO_ROOT / "rule-catalog" / "operator-console",
        workflow_names={workflow.name for workflow in workflows},
        view_workflows={spec.id: spec.applies_to.workflow_ref for spec in view_specs},
    )
    view_engine = ViewEngine(specs=view_specs, reports=report_engine, processes=runtime)
    action_types_by_name = {action_type.name: action_type for action_type in action_types}
    from fdai.core.architecture_review import ArchitectureReviewProductionGateEvaluator

    workflow_orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=action_types_by_name,
            group_mapping=_group_mapping_from_env(),
            matrix=load_matrix_from_yaml(_REPO_ROOT / "config" / "notifications-matrix.yaml"),
        ),
        action_types=action_types_by_name,
        audit_store=InMemoryStateStore(),
        process_store=runtime,
        guard_evaluator=ArchitectureReviewProductionGateEvaluator(
            manifest_path=_REPO_ROOT / "config" / "architecture-review.yaml",
            repo_root=_REPO_ROOT,
        ),
    )
    return (
        ReportingConfig(engine=report_engine, formats=formats),
        ProcessViewsConfig(
            engine=view_engine,
            apps=workflow_apps,
            source="synthetic-dev",
            synthetic=True,
            durable=False,
        ),
        WorkflowExecutionConfig(
            workflows=workflows,
            orchestrator=workflow_orchestrator,
        ),
    )
