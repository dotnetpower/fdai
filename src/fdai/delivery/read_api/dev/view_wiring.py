"""Catalog-driven view and user-context wiring for the local read API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fdai.core.architecture_review import ArchitectureReviewProductionGateEvaluator
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import RenderedReport
from fdai.core.views import ViewEngine
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.delivery.read_api.dev.catalog_wiring import (
    LocalCatalogWiring,
    build_local_catalog_wiring,
)
from fdai.delivery.read_api.dev.config import group_mapping_from_env
from fdai.delivery.read_api.dev.fixtures.dynamic_views import (
    _build_dynamic_process_views_sync,
)
from fdai.delivery.read_api.dev.user_context import build_local_user_context
from fdai.delivery.read_api.routes.process_views import ProcessViewsConfig
from fdai.delivery.read_api.routes.workflow_execution import WorkflowExecutionConfig
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore, InMemoryStateStore


class _NoLocalReports:
    async def render(self, report_id: str, *, variables: dict[str, str]) -> RenderedReport:
        del variables
        raise KeyError(f"local Process has no report view {report_id!r}")


@dataclass(frozen=True, slots=True)
class LocalViewWiring:
    catalog: LocalCatalogWiring
    reporting: Any
    process_views: Any
    workflow_execution: Any
    user_context: Any


def build_local_view_wiring(
    *,
    repo_root: Path,
    read_model: Any,
    include_test_fixtures: bool = False,
) -> LocalViewWiring:
    """Build local catalogs, dynamic process views, and user context."""
    catalog = build_local_catalog_wiring(
        repo_root,
        include_test_fixtures=include_test_fixtures,
    )
    reporting = None
    process_views = None
    workflow_execution = None
    if include_test_fixtures and catalog.object_types and catalog.link_types and catalog.workflows:
        reporting, process_views, workflow_execution = _build_dynamic_process_views_sync(
            read_model=read_model,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
            workflows=catalog.workflows,
            action_types=catalog.action_types,
        )
    elif catalog.workflows:
        process_store = InMemoryProcessRuntimeStore()
        action_types_by_name = {item.name: item for item in catalog.action_types}
        workflow_execution = WorkflowExecutionConfig(
            workflows=catalog.workflows,
            orchestrator=WorkflowOrchestrator(
                planner=WorkflowApprovalPlanner(
                    action_types=action_types_by_name,
                    group_mapping=group_mapping_from_env(),
                    matrix=load_matrix_from_yaml(
                        repo_root / "config" / "notifications-matrix.yaml"
                    ),
                ),
                action_types=action_types_by_name,
                audit_store=InMemoryStateStore(),
                process_store=process_store,
                guard_evaluator=ArchitectureReviewProductionGateEvaluator(
                    manifest_path=repo_root / "config" / "architecture-review.yaml",
                    repo_root=repo_root,
                ),
            ),
        )
        process_views = ProcessViewsConfig(
            engine=ViewEngine(
                specs=(),
                reports=cast(ReportEngine, _NoLocalReports()),
                processes=process_store,
            ),
            source="local-runtime",
            synthetic=False,
            durable=False,
        )
    user_context = build_local_user_context(
        schema_registry=catalog.schema_registry,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        workflows=catalog.workflows,
        rule_ids=frozenset(rule.id for rule in catalog.rules if getattr(rule, "id", None)),
    )
    return LocalViewWiring(
        catalog=catalog,
        reporting=reporting,
        process_views=process_views,
        workflow_execution=workflow_execution,
        user_context=user_context,
    )


__all__ = ["LocalViewWiring", "build_local_view_wiring"]
