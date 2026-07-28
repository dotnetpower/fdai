"""Stable local-development read API factory facade."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

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
from fdai.shared.telemetry import configure_logging

_QUIET_DEPENDENCY_LOGGERS = ("aiokafka", "httpx", "weasyprint")


def _configure_server_logging(environ: Mapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    level_name = env.get("FDAI_LOG_LEVEL", "INFO").upper().strip()
    configured_level = getattr(logging, level_name, logging.INFO)
    if not isinstance(configured_level, int):
        configured_level = logging.INFO
    configure_logging(level=configured_level)
    for logger_name in _QUIET_DEPENDENCY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def app(*, test_fixtures: bool = False) -> Starlette:
    return build_local_app(
        identity_resolver=resolve_azure_cli_identity,
        test_fixtures=test_fixtures,
    )


def server_app() -> Starlette:
    _configure_server_logging()
    return app()


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
    "server_app",
]
