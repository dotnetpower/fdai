"""Optional projection and workflow route registration groups."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.core.rbac.resolver import Principal
from fdai.delivery.operator_api.app.composition import ProjectionRouteBindings
from fdai.delivery.operator_api.routes.scope import append_scope_route


def append_projection_routes(
    routes: list[BaseRoute],
    *,
    bindings: ProjectionRouteBindings,
    authorize: Callable[[Request], Awaitable[str]],
    authorize_principal: Callable[[Request], Awaitable[Principal]],
    core_paths: frozenset[str],
    panel_paths: set[str],
) -> None:
    """Append optional projections in their established registration order."""
    if bindings.blast_radius_graph is not None:
        from fdai.delivery.operator_api.routes.blast_radius import (
            DEFAULT_ROUTE_PATH,
            make_blast_radius_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "blast-radius path", core_paths, panel_paths)
        routes.append(
            make_blast_radius_route(graph=bindings.blast_radius_graph, authorize=authorize)
        )

    if bindings.ontology_object_types and bindings.ontology_link_types:
        from fdai.delivery.operator_api.routes.ontology_graph import (
            DEFAULT_ROUTE_PATH,
            make_ontology_graph_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "ontology-graph path", core_paths, panel_paths)
        routes.append(
            make_ontology_graph_route(
                object_types=bindings.ontology_object_types,
                link_types=bindings.ontology_link_types,
                action_types=bindings.ontology_action_types,
                function_types=bindings.ontology_function_types,
                status_reader=bindings.operating_model_status_reader,
                authorize=authorize,
            )
        )

    if bindings.inventory_graph_provider is not None:
        from fdai.delivery.operator_api.routes.inventory_graph import (
            DEFAULT_ROUTE_PATH,
            make_inventory_graph_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "inventory-graph path", core_paths, panel_paths)
        routes.append(
            make_inventory_graph_route(
                provider=bindings.inventory_graph_provider,
                authorize=authorize,
            )
        )

    if bindings.detection_readiness_reader is not None:
        from fdai.delivery.operator_api.routes.detection_readiness import (
            DEFAULT_ROUTE_PATH,
            make_detection_readiness_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "detection-readiness path", core_paths, panel_paths)
        routes.append(
            make_detection_readiness_route(
                reader=bindings.detection_readiness_reader,
                authorize=authorize,
            )
        )

    if bindings.best_practice_controls:
        from fdai.delivery.operator_api.routes.best_practices import (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            make_best_practice_routes,
        )

        for path in (DEFAULT_ROUTE_PATH, DETAIL_ROUTE_PATH):
            _ensure_available(path, "best-practice path", core_paths, panel_paths)
        routes.extend(
            make_best_practice_routes(
                controls=bindings.best_practice_controls,
                authorize=authorize,
            )
        )

    if bindings.mcsb_catalogs:
        from fdai.delivery.operator_api.routes.mcsb_controls import (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            make_mcsb_control_routes,
        )

        for path in (DEFAULT_ROUTE_PATH, DETAIL_ROUTE_PATH):
            _ensure_available(path, "MCSB control path", core_paths, panel_paths)
        routes.extend(
            make_mcsb_control_routes(
                catalogs=bindings.mcsb_catalogs,
                authorize=authorize,
            )
        )

    if bindings.rule_catalog_rules or bindings.rule_catalog_collected_rules:
        from fdai.delivery.operator_api.routes.rule_catalog import (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            FINDINGS_ROUTE_PATH,
            FINDINGS_SUMMARY_ROUTE_PATH,
            SEARCH_ROUTE_PATH,
            make_rule_catalog_routes,
        )

        for path in (
            DEFAULT_ROUTE_PATH,
            DETAIL_ROUTE_PATH,
            FINDINGS_ROUTE_PATH,
            FINDINGS_SUMMARY_ROUTE_PATH,
            SEARCH_ROUTE_PATH,
        ):
            _ensure_available(path, "rule-catalog path", core_paths, panel_paths)
        routes.extend(
            make_rule_catalog_routes(
                active_rules=bindings.rule_catalog_rules,
                collected_rules=bindings.rule_catalog_collected_rules,
                authorize=authorize,
                policies_root=bindings.rule_catalog_policies_root,
                remediation_root=bindings.rule_catalog_remediation_root,
                findings_provider=bindings.rule_catalog_findings_provider,
                findings_summary_provider=bindings.rule_catalog_findings_summary_provider,
                semantic_index=bindings.rule_catalog_semantic_index,
                query_registry=bindings.rule_catalog_query_registry,
            )
        )

    if bindings.promotion_gate_action_types and bindings.promotion_gate_source is not None:
        from fdai.delivery.operator_api.routes.promotion_gates import (
            DEFAULT_ROUTE_PATH,
            make_promotion_gates_route,
        )

        _ensure_available(DEFAULT_ROUTE_PATH, "promotion-gates path", core_paths, panel_paths)
        routes.append(
            make_promotion_gates_route(
                action_types=bindings.promotion_gate_action_types,
                source=bindings.promotion_gate_source,
                authorize=authorize,
            )
        )

    append_scope_route(routes, bindings.scope_source, authorize, core_paths, panel_paths)

    if bindings.stewardship_map is not None:
        from fdai.delivery.operator_api.routes.stewardship import (
            ROUTE_PATH,
            make_stewardship_route,
        )

        _ensure_available(ROUTE_PATH, "stewardship path", core_paths, panel_paths)
        routes.append(
            make_stewardship_route(
                stewardship_map=bindings.stewardship_map,
                authorize=authorize,
                health_reader=bindings.stewardship_health_reader,
            )
        )

    if bindings.workflow_authoring is not None:
        from fdai.delivery.operator_api.routes.workflow_authoring import (
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
                config=bindings.workflow_authoring,
                authorize=authorize,
            )
        )
        routes.append(
            make_workflow_validate_route(config=bindings.workflow_authoring, authorize=authorize)
        )
        routes.append(
            make_workflow_catalog_route(config=bindings.workflow_authoring, authorize=authorize)
        )

    from fdai.delivery.operator_api.routes.workflow_execution import append_workflow_run_route

    append_workflow_run_route(
        routes,
        config=bindings.workflow_execution,
        authorize_principal=authorize_principal,
        core_paths=core_paths,
        panel_paths=panel_paths,
    )

    if bindings.python_tasks is not None:
        from fdai.delivery.operator_api.routes.python_tasks import build_python_task_routes

        routes.extend(
            build_python_task_routes(
                config=bindings.python_tasks,
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
