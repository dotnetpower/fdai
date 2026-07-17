"""Stable local-development read API factory facade."""

from __future__ import annotations

from starlette.applications import Starlette

from fdai.delivery.read_api.dev.azure_cli_identity import resolve_azure_cli_identity
from fdai.delivery.read_api.dev.factory import (
    _build_agent_streams,
    _build_chat_backend,
    _build_chat_web_search,
    _build_inventory_graph_provider,
    _build_live_stream_config,
    _build_stewardship_map,
    _chat_probe_interval_seconds,
    _cors_origins_from_env,
    _group_mapping_from_env,
    build_local_app,
)
from fdai.delivery.read_api.dev.fixtures.dynamic_views import (
    _build_blast_radius_graph,
    _build_dynamic_process_views,
    _build_dynamic_process_views_sync,
    _build_scope_view,
)
from fdai.delivery.read_api.dev.fixtures.seed_data import (
    _seed,
    _seed_trace,
    _synthetic_llm_invocations,
    _synthetic_verdicts,
)


def app() -> Starlette:
    return build_local_app(identity_resolver=resolve_azure_cli_identity)


__all__ = [
    "_build_agent_streams",
    "_build_blast_radius_graph",
    "_build_chat_backend",
    "_build_chat_web_search",
    "_build_dynamic_process_views",
    "_build_dynamic_process_views_sync",
    "_build_inventory_graph_provider",
    "_build_live_stream_config",
    "_build_scope_view",
    "_build_stewardship_map",
    "_chat_probe_interval_seconds",
    "_cors_origins_from_env",
    "_group_mapping_from_env",
    "_seed",
    "_seed_trace",
    "_synthetic_llm_invocations",
    "_synthetic_verdicts",
    "app",
]
