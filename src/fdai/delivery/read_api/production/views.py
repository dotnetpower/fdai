"""Production ontology, workflow, report, and dynamic-view assembly."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.report_feed import ReportFeed
from fdai.core.reporting.composition import default_reporting_engine
from fdai.core.reporting.datasources import AuditReader
from fdai.core.views import ViewEngine, load_view_catalog
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.delivery.persistence import (
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
    PostgresStateStore,
)
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.read_api.postgres_read_model import PostgresConsoleReadModel
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.delivery.read_api.routes.reporting import ReportingConfig
from fdai.delivery.read_api.routes.workflow_authoring import WorkflowAuthoringConfig
from fdai.delivery.read_api.routes.workflow_execution import WorkflowExecutionConfig
from fdai.delivery.reporting import install_pdf_format_if_available
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
    Workflow,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _build_dynamic_views(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    read_model: PostgresConsoleReadModel,
    group_mapping: GroupMapping,
) -> tuple[
    ReportingConfig,
    ProcessViewsConfig,
    tuple[OntologyObjectType, ...],
    tuple[OntologyLinkType, ...],
    tuple[OntologyActionType, ...],
    tuple[Workflow, ...],
    WorkflowAuthoringConfig,
    WorkflowExecutionConfig,
]:
    schema_registry = PackageResourceSchemaRegistry()
    object_types = load_object_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types",
        schema_registry=schema_registry,
    )
    link_types = load_link_type_catalog(
        _REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types",
        schema_registry=schema_registry,
        object_types=object_types,
    )
    action_types = load_action_type_catalog(
        _REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=schema_registry,
        probes_root=None,
    )
    workflows = load_workflow_catalog(
        _REPO_ROOT / "rule-catalog" / "workflows",
        schema_registry=schema_registry,
        action_type_names={item.name for item in action_types},
    )
    process_store = PostgresProcessRuntimeStore(
        config=PostgresProcessRuntimeStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        ),
        object_types=object_types,
        link_types=link_types,
    )
    report_signal_store = PostgresReportSignalStore(
        config=PostgresReportSignalStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    report_engine, formats = default_reporting_engine(
        reports_root=_REPO_ROOT / "rule-catalog" / "reports",
        audit_reader=cast(AuditReader, read_model),
        report_feed=ReportFeed((report_signal_store,)),
        ontology_store=ontology_store,
        process_store=process_store,
    )
    install_pdf_format_if_available(formats)
    view_specs = load_view_catalog(
        _REPO_ROOT / "rule-catalog" / "views",
        report_ids={spec.id for spec in report_engine.catalog().list()},
        workflow_names={workflow.name for workflow in workflows},
    )
    action_types_by_name = {action_type.name: action_type for action_type in action_types}
    workflow_execution = WorkflowExecutionConfig(
        workflows=tuple(workflows),
        orchestrator=WorkflowOrchestrator(
            planner=WorkflowApprovalPlanner(
                action_types=action_types_by_name,
                group_mapping=group_mapping,
                matrix=load_matrix_from_yaml(_REPO_ROOT / "config" / "notifications-matrix.yaml"),
            ),
            action_types=action_types_by_name,
            audit_store=PostgresStateStore(
                config=PostgresStateStoreConfig(
                    dsn=dsn,
                    statement_timeout_ms=statement_timeout_ms,
                    connect_timeout_s=connect_timeout_s,
                )
            ),
            process_store=process_store,
        ),
    )
    workflow_authoring = WorkflowAuthoringConfig(
        schema_registry=schema_registry,
        action_types=tuple(action_types),
        workflows=tuple(workflows),
    )
    return (
        ReportingConfig(engine=report_engine, formats=formats),
        ProcessViewsConfig(
            engine=ViewEngine(specs=view_specs, reports=report_engine, processes=process_store),
            source="postgres",
            synthetic=False,
            durable=True,
        ),
        tuple(object_types),
        tuple(link_types),
        tuple(action_types),
        tuple(workflows),
        workflow_authoring,
        workflow_execution,
    )
