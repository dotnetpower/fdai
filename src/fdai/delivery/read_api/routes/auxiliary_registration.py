"""Register optional dynamic, conversational, and user-owned read API routes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from starlette.requests import Request
from starlette.routing import BaseRoute, Route

from fdai.delivery.read_api.routes import chat_registration, dynamic_views

AuthorizeFn = Callable[[Request], Awaitable[str]]
AuthorizePrincipalFn = Callable[[Request], Awaitable[Any]]


def append_auxiliary_routes(
    routes: list[BaseRoute],
    *,
    config: Any,
    authorize: AuthorizeFn,
    authorize_principal: AuthorizePrincipalFn,
    read_model: Any,
    core_paths: frozenset[str],
    seen_panel_paths: set[str],
    logger: logging.Logger,
) -> None:
    """Append optional projections after the fixed route surface is assembled."""

    seen_panel_paths.update(route.path for route in routes if isinstance(route, Route))
    routes.extend(
        dynamic_views.build_dynamic_view_routes(
            reporting=config.reporting,
            process_views=config.process_views,
            authorize=authorize,
            core_paths=core_paths,
            seen_extra_paths=seen_panel_paths,
        )
    )

    trace_reader = config.trace_reader
    if trace_reader is None:
        from fdai.delivery.read_api.routes.rule_fire_trace_reader import (
            ConsoleReadModelTraceReader,
        )

        trace_reader = ConsoleReadModelTraceReader(read_model)
    if trace_reader is not None:
        from fdai.delivery.read_api.routes.rule_fire_trace import (
            make_rule_fire_trace_route,
        )

        routes.append(make_rule_fire_trace_route(reader=trace_reader, authorize=authorize))

    if config.bitemporal_reader is not None:
        from fdai.delivery.read_api.routes.bitemporal import make_bitemporal_route

        routes.append(make_bitemporal_route(reader=config.bitemporal_reader, authorize=authorize))

    if config.what_if_reader is not None and config.what_if_evaluators:
        from fdai.delivery.read_api.routes.what_if import make_what_if_route

        routes.append(
            make_what_if_route(
                reader=config.what_if_reader,
                evaluators=dict(config.what_if_evaluators),
                authorize=authorize,
            )
        )

    chat_registration.append_chat_routes(
        routes,
        backend=config.chat,
        skill_disclosure=config.skill_disclosure,
        busy_input_runtime=config.busy_input_runtime,
        agent_delegate=config.chat_agent_delegate,
        web_search_resolver=config.chat_web_search,
        conversation_policy_store=config.conversation_policy_store,
        conversation_history_store=config.conversation_history_store,
        conversation_search=config.conversation_search,
        inventory_graph_provider=config.inventory_graph_provider,
        log_query_provider=config.log_query_provider,
        answer_preference_store=(
            config.user_context.preferences if config.user_context is not None else None
        ),
        post_turn_review_submitter=config.post_turn_review_submitter,
        user_context_ontology_projector=config.user_context_ontology_projector,
        model_settings=config.model_settings,
        authorize=authorize,
        read_model=read_model,
        core_paths=core_paths,
        panel_paths=seen_panel_paths,
        logger=logger,
    )

    if config.user_context is not None:
        from fdai.delivery.read_api.routes.user_context import make_user_context_routes

        routes.extend(make_user_context_routes(config=config.user_context, authorize=authorize))

    if config.task_worker_store is not None:
        from fdai.delivery.read_api.routes.task_workers import make_task_worker_routes

        routes.extend(make_task_worker_routes(store=config.task_worker_store, authorize=authorize))

    if config.background_tasks is not None:
        from fdai.delivery.read_api.routes.background_tasks import (
            make_background_task_routes,
        )

        routes.extend(
            make_background_task_routes(
                config=config.background_tasks,
                authorize_principal=authorize_principal,
            )
        )

    if config.trajectory_datasets is not None:
        from fdai.delivery.read_api.routes.trajectory_datasets import (
            make_trajectory_dataset_routes,
        )

        routes.extend(
            make_trajectory_dataset_routes(
                service=config.trajectory_datasets,
                authorize_principal=authorize_principal,
            )
        )

    if config.skill_sources is not None:
        from fdai.delivery.read_api.routes.skill_sources import make_skill_source_routes

        routes.extend(
            make_skill_source_routes(
                config=config.skill_sources,
                authorize_principal=authorize_principal,
            )
        )

    if config.model_settings is not None:
        from fdai.delivery.read_api.routes.model_settings import make_model_settings_routes

        routes.extend(
            make_model_settings_routes(
                service=config.model_settings,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )

    if config.workflow_definitions is not None:
        from fdai.delivery.read_api.routes.workflow_definitions import (
            make_workflow_definition_routes,
        )

        routes.extend(
            make_workflow_definition_routes(
                config=config.workflow_definitions,
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
