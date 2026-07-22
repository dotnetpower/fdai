"""Optional projection and workflow route registration groups."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.rbac.resolver import Principal
from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.routes.pantheon import append_pantheon_routes
from fdai.delivery.read_api.routes.scope import append_scope_route


def append_projection_routes(
    routes: list[BaseRoute],
    *,
    config: ReadApiConfig,
    authorize: Callable[[Request], Awaitable[str]],
    authorize_principal: Callable[[Request], Awaitable[Principal]],
    core_paths: frozenset[str],
    panel_paths: set[str],
) -> None:
    """Append optional projections in their established registration order."""
    if config.blast_radius_graph is not None:
        from fdai.delivery.read_api.routes.blast_radius import (
            DEFAULT_ROUTE_PATH,
            make_blast_radius_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "blast-radius path", core_paths, panel_paths)
        routes.append(make_blast_radius_route(graph=config.blast_radius_graph, authorize=authorize))

    if config.ontology_object_types and config.ontology_link_types:
        from fdai.delivery.read_api.routes.ontology_graph import (
            DEFAULT_ROUTE_PATH,
            make_ontology_graph_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "ontology-graph path", core_paths, panel_paths)
        routes.append(
            make_ontology_graph_route(
                object_types=config.ontology_object_types,
                link_types=config.ontology_link_types,
                action_types=config.ontology_action_types,
                authorize=authorize,
            )
        )

    if config.inventory_graph_provider is not None:
        from fdai.delivery.read_api.routes.inventory_graph import (
            DEFAULT_ROUTE_PATH,
            make_inventory_graph_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "inventory-graph path", core_paths, panel_paths)
        routes.append(
            make_inventory_graph_route(
                provider=config.inventory_graph_provider,
                authorize=authorize,
            )
        )

    if config.rule_catalog_rules or config.rule_catalog_collected_rules:
        from fdai.delivery.read_api.routes.rule_catalog import (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            FINDINGS_ROUTE_PATH,
            FINDINGS_SUMMARY_ROUTE_PATH,
            make_rule_catalog_routes,
        )

        for path in (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            FINDINGS_ROUTE_PATH,
            FINDINGS_SUMMARY_ROUTE_PATH,
        ):
            _ensure_available(path, "rule-catalog path", core_paths, panel_paths)
        routes.extend(
            make_rule_catalog_routes(
                active_rules=config.rule_catalog_rules,
                collected_rules=config.rule_catalog_collected_rules,
                authorize=authorize,
                policies_root=config.rule_catalog_policies_root,
                remediation_root=config.rule_catalog_remediation_root,
                findings_provider=config.rule_catalog_findings_provider,
                findings_summary_provider=config.rule_catalog_findings_summary_provider,
            )
        )

    if config.promotion_gate_action_types and config.promotion_gate_source is not None:
        from fdai.delivery.read_api.routes.promotion_gates import (
            DEFAULT_ROUTE_PATH,
            make_promotion_gates_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "promotion-gates path", core_paths, panel_paths)
        routes.append(
            make_promotion_gates_route(
                action_types=config.promotion_gate_action_types,
                source=config.promotion_gate_source,
                authorize=authorize,
            )
        )

    append_scope_route(routes, config.scope_source, authorize, core_paths, panel_paths)
    append_pantheon_routes(routes, config.expose_pantheon, authorize, core_paths, panel_paths)

    if config.stewardship_map is not None:
        from fdai.delivery.read_api.routes.stewardship import (
            ROUTE_PATH,
            make_stewardship_route,
        )

        _ensure_available(ROUTE_PATH, "stewardship path", core_paths, panel_paths)
        routes.append(
            make_stewardship_route(
                stewardship_map=config.stewardship_map,
                authorize=authorize,
                health_reader=config.stewardship_health_reader,
            )
        )

    if config.workflow_authoring is not None:
        from fdai.delivery.read_api.routes.workflow_authoring import (
            ACTION_TYPES_ROUTE_PATH,
            CATALOG_ROUTE_PATH,
            VALIDATE_ROUTE_PATH,
            make_action_types_route,
            make_workflow_catalog_route,
            make_workflow_validate_route,
        )

        for path in (ACTION_TYPES_ROUTE_PATH, VALIDATE_ROUTE_PATH, CATALOG_ROUTE_PATH):
            _ensure_available(path, "workflow authoring path", core_paths, panel_paths)
        routes.append(
            make_action_types_route(
                config=config.workflow_authoring,
                authorize=authorize,
            )
        )
        routes.append(
            make_workflow_validate_route(config=config.workflow_authoring, authorize=authorize)
        )
        routes.append(
            make_workflow_catalog_route(config=config.workflow_authoring, authorize=authorize)
        )

    from fdai.delivery.read_api.routes.workflow_execution import append_workflow_run_route

    append_workflow_run_route(
        routes,
        config=config.workflow_execution,
        authorize_principal=authorize_principal,
        core_paths=core_paths,
        panel_paths=panel_paths,
    )

    if config.python_tasks is not None:
        from fdai.delivery.read_api.routes.python_tasks import build_python_task_routes

        routes.extend(
            build_python_task_routes(
                config=config.python_tasks,
                authorize_oid=authorize,
                authorize_principal=authorize_principal,
            )
        )


def _ensure_available(
    path: str,
    label: str,
    core_paths: Collection[str],
    panel_paths: Collection[str],
) -> None:
    if path in core_paths:
        raise ValueError(f"{label} {path!r} collides with a core route")
    if path in panel_paths:
        raise ValueError(f"{label} {path!r} collides with a panel path")


__all__ = ["append_projection_routes"]
