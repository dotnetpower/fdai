"""Register optional dynamic, conversational, and user-owned Operator API routes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from starlette.requests import Request
from starlette.routing import BaseRoute, Route

from fdai.delivery.operator_api.app.composition import (
    ConversationRouteBindings,
    GovernedRouteBindings,
    ReadViewBindings,
)
from fdai.delivery.operator_api.routes import chat_registration, dynamic_views

AuthorizeFn = Callable[[Request], Awaitable[str]]
AuthorizePrincipalFn = Callable[[Request], Awaitable[Any]]


def append_auxiliary_routes(
    routes: list[BaseRoute],
    *,
    read_views: ReadViewBindings,
    conversation: ConversationRouteBindings,
    governed: GovernedRouteBindings,
    authorize: AuthorizeFn,
    authorize_principal: AuthorizePrincipalFn,
    read_model: Any,
    core_paths: frozenset[str],
    seen_panel_paths: set[str],
    logger: logging.Logger,
) -> None:
    """Append optional projections after the fixed route surface is assembled."""

    registered_paths = set(seen_panel_paths)
    registered_paths.update(route.path for route in routes if isinstance(route, Route))
    dynamic_routes = dynamic_views.build_dynamic_view_routes(
        reporting=read_views.reporting,
        process_views=read_views.process_views,
        authorize=authorize,
        core_paths=core_paths,
        seen_extra_paths=registered_paths,
    )
    routes.extend(dynamic_routes)
    seen_panel_paths.update(route.path for route in dynamic_routes)

    trace_reader = read_views.trace_reader
    if trace_reader is None:
        from fdai.delivery.operator_api.routes.rule_fire_trace_reader import (
            ConsoleReadModelTraceReader,
        )

        trace_reader = ConsoleReadModelTraceReader(read_model)
    if trace_reader is not None:
        from fdai.delivery.operator_api.routes.rule_fire_trace import (
            make_rule_fire_trace_route,
        )

        routes.append(make_rule_fire_trace_route(reader=trace_reader, authorize=authorize))

    if read_views.bitemporal_reader is not None:
        from fdai.delivery.operator_api.routes.bitemporal import make_bitemporal_route

        routes.append(
            make_bitemporal_route(reader=read_views.bitemporal_reader, authorize=authorize)
        )

    if read_views.what_if_reader is not None and read_views.what_if_evaluators:
        from fdai.delivery.operator_api.routes.what_if import make_what_if_route

        routes.append(
            make_what_if_route(
                reader=read_views.what_if_reader,
                evaluators=dict(read_views.what_if_evaluators),
                authorize=authorize,
            )
        )

    chat_registration.append_chat_routes(
        routes,
        backend=conversation.chat,
        skill_disclosure=conversation.skill_disclosure,
        knowledge_context=conversation.knowledge_context,
        configuration_drift_context=conversation.configuration_drift_context,
        busy_input_runtime=conversation.busy_input_runtime,
        progress_metrics=conversation.conversation_progress_metrics,
        agent_delegate=conversation.chat_agent_delegate,
        web_search_resolver=conversation.chat_web_search,
        conversation_policy_store=conversation.conversation_policy_store,
        conversation_assurance_runtime=conversation.conversation_assurance_runtime,
        conversation_history_store=conversation.conversation_history_store,
        conversation_image_store=(
            conversation.user_context.images if conversation.user_context is not None else None
        ),
        conversation_search=conversation.conversation_search,
        llm_usage_reader=conversation.llm_usage_reader,
        inventory_graph_provider=conversation.inventory_graph_provider,
        inventory_semantic_resolver=conversation.inventory_semantic_resolver,
        inventory_activity_provider=conversation.inventory_activity_provider,
        kubernetes_workload_provider=conversation.kubernetes_workload_provider,
        detection_readiness_reader=conversation.detection_readiness_reader,
        t2_recovery_reader=conversation.t2_recovery_reader,
        subscription_health_provider=conversation.subscription_health_provider,
        log_query_provider=conversation.log_query_provider,
        network_reachability_provider=conversation.network_reachability_provider,
        data_sources=conversation.data_sources,
        answer_preference_store=(
            conversation.user_context.preferences if conversation.user_context is not None else None
        ),
        post_turn_review_submitter=conversation.post_turn_review_submitter,
        document_evidence_resolver=conversation.chat_document_evidence,
        user_context_ontology_projector=conversation.user_context_ontology_projector,
        model_settings=conversation.model_settings,
        console_action=conversation.console_action,
        handover_availability_publisher=conversation.handover_availability_publisher,
        authorize=authorize,
        read_model=read_model,
        panels=conversation.extra_panels,
        core_paths=core_paths,
        panel_paths=seen_panel_paths,
        logger=logger,
    )

    if conversation.user_context is not None:
        from fdai.delivery.operator_api.routes.user_context import make_user_context_routes

        routes.extend(
            make_user_context_routes(config=conversation.user_context, authorize=authorize)
        )

    if governed.handover_goals is not None:
        from fdai.delivery.operator_api.routes.handover_goals import make_handover_goal_routes

        routes.extend(
            make_handover_goal_routes(
                service=governed.handover_goals,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )

    if governed.task_worker_store is not None:
        from fdai.delivery.operator_api.routes.task_workers import make_task_worker_routes

        routes.extend(
            make_task_worker_routes(store=governed.task_worker_store, authorize=authorize)
        )

    if governed.background_tasks is not None:
        from fdai.delivery.operator_api.routes.background_tasks import (
            make_background_task_routes,
        )

        routes.extend(
            make_background_task_routes(
                config=governed.background_tasks,
                authorize_principal=authorize_principal,
            )
        )

    if governed.read_investigations is not None:
        from fdai.delivery.operator_api.routes.read_investigations import (
            make_read_investigation_routes,
        )

        routes.extend(
            make_read_investigation_routes(
                config=governed.read_investigations,
                authorize_principal=authorize_principal,
            )
        )

    if governed.trajectory_datasets is not None:
        from fdai.delivery.operator_api.routes.trajectory_datasets import (
            make_trajectory_dataset_routes,
        )

        routes.extend(
            make_trajectory_dataset_routes(
                service=governed.trajectory_datasets,
                authorize_principal=authorize_principal,
            )
        )

    if governed.skill_sources is not None:
        from fdai.delivery.operator_api.routes.skill_sources import make_skill_source_routes

        routes.extend(
            make_skill_source_routes(
                config=governed.skill_sources,
                authorize_principal=authorize_principal,
            )
        )

    if governed.model_settings is not None:
        from fdai.delivery.operator_api.routes.model_settings import make_model_settings_routes

        routes.extend(
            make_model_settings_routes(
                service=governed.model_settings,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )

    if governed.runtime_settings is not None:
        from fdai.delivery.operator_api.routes.runtime_settings import make_runtime_settings_routes

        routes.extend(
            make_runtime_settings_routes(
                service=governed.runtime_settings,
                authorize_principal=authorize_principal,
            )
        )

    if governed.workflow_definitions is not None:
        from fdai.delivery.operator_api.routes.workflow_definitions import (
            make_workflow_definition_routes,
        )

        routes.extend(
            make_workflow_definition_routes(
                config=governed.workflow_definitions,
                authorize=authorize,
            )
        )


def registered_cors_methods(routes: Collection[BaseRoute]) -> list[str]:
    return sorted(
        {
            method
            for route in routes
            for method in (getattr(route, "methods", None) or ())
            if method not in {"HEAD", "OPTIONS"}
        }
    )


__all__ = ["append_auxiliary_routes", "registered_cors_methods"]
