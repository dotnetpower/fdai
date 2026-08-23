"""Headless control-plane process lifecycle and shutdown coordination."""

from __future__ import annotations

import logging
import os
from typing import Any

from fdai.composition import (
    LlmBindings,
    default_container_from_env,
)
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    case_history_identity_client_id as _case_history_identity_client_id,
)
from fdai.runtime.bootstrap_core import (
    CoreRuntime,
    build_core_runtime,
)
from fdai.runtime.bootstrap_lifecycle import (
    bind_health_readiness,
    install_shutdown_signals,
    open_health_port,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_main as _run_main,
)
from fdai.runtime.bootstrap_plan import build_bootstrap_plan
from fdai.runtime.bootstrap_resources import RuntimeResources
from fdai.runtime.bootstrap_task_hooks import default_runtime_task_hooks
from fdai.runtime.bootstrap_tasks import (
    run_runtime_tasks,
)
from fdai.runtime.bootstrap_tasks import (
    schedule_semantic_turn_consumer as _schedule_semantic_turn_consumer,
)
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS as _RUNTIME_LOGICAL_TOPICS
from fdai.runtime.configuration import (
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _summarize_config,
)
from fdai.shared.config.models import LlmMode
from fdai.shared.config.runtime_flags import pantheon_start_enabled

_LOGGER = logging.getLogger("fdai.startup")
__all__ = [
    "_RUNTIME_LOGICAL_TOPICS",
    "_run",
    "_schedule_semantic_turn_consumer",
    "main",
]


async def _run() -> int:
    container = default_container_from_env()
    plan = build_bootstrap_plan(
        llm_mode=container.config.llm.mode,
        environment=os.environ,
    )
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    resources = RuntimeResources()
    identity: Any = None

    try:
        resources.health_server = await open_health_port()
        identity_requests = plan.identity_requests
        if identity_requests.case_history:
            _case_history_identity_client_id(os.environ)
        if plan.requires_initial_identity:
            resources.http_client = _new_http_client()
            identity = _build_runtime_workload_identity(resources.http_client)

        if container.config.llm.mode == LlmMode.AZURE:
            if resources.http_client is None or identity is None:
                raise RuntimeError("Azure LLM mode requires HTTP and workload identity bindings")
            container = await _finalize_llm_bindings(
                container, http_client=resources.http_client, identity=identity
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )
        elif identity_requests.telemetry:
            if resources.http_client is None or identity is None:
                raise RuntimeError("Azure telemetry requires HTTP and workload identity bindings")
            container = _attach_runtime_metric_provider(
                container,
                http_client=resources.http_client,
                identity=identity,
            )
            container = _attach_runtime_knowledge_source(container)

        core_runtime: CoreRuntime | None = None
        if plan.start_consumer:
            if identity is None and plan.consumer_requires_workload_identity:
                if resources.http_client is None:
                    resources.http_client = _new_http_client()
                identity = _build_runtime_workload_identity(resources.http_client)
            core_runtime = await build_core_runtime(
                container=container,
                plan=plan,
                resources=resources,
                identity=identity,
                environment=os.environ,
            )
        elif pantheon_start_enabled(os.environ):
            # Pantheon needs the same Kafka bus the consumer builds; without
            # FDAI_START_CONSUMER there is no bus to bind to. Warn rather
            # than silently no-op so a miswired container is visible.
            _LOGGER.warning("pantheon_requested_without_consumer")

        bind_health_readiness(
            resources.health_server,
            control_loop=(core_runtime.control_loop if core_runtime is not None else None),
            startup_readiness=(core_runtime.readiness if core_runtime is not None else None),
        )
        stop = install_shutdown_signals()
        if core_runtime is not None:
            await run_runtime_tasks(
                core_runtime.task_configuration(stop),
                default_runtime_task_hooks(),
            )
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        await resources.close()


def main() -> int:
    return _run_main(_run)
