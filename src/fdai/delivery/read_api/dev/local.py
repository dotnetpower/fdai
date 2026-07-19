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


def app(*, test_fixtures: bool = False) -> Starlette:
    return build_local_app(
        identity_resolver=resolve_azure_cli_identity,
        test_fixtures=test_fixtures,
    )


__all__ = [
    "_build_agent_streams",
    "_build_chat_backend",
    "_build_chat_web_search",
    "_build_inventory_graph_provider",
    "_build_live_stream_config",
    "_build_stewardship_map",
    "_chat_probe_interval_seconds",
    "_cors_origins_from_env",
    "_group_mapping_from_env",
    "app",
]
