"""Configuration, health, and shutdown helpers for runtime bootstrap."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable, Coroutine
from typing import Any

from fdai.agents import Saga, SemanticRouterConfig, StateStoreAuditChainAdapter
from fdai.core.control_loop import ControlLoop
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.readiness import StartupReadinessRuntime
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")


def semantic_router_config_from_env() -> SemanticRouterConfig:
    def setting(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} MUST be a float") from exc

    return SemanticRouterConfig(
        cosine_threshold=setting("FDAI_AGENT_SEMANTIC_COSINE_THRESHOLD", 0.65),
        margin_threshold=setting("FDAI_AGENT_SEMANTIC_MARGIN_THRESHOLD", 0.08),
    )


def build_runtime_saga(state_store: StateStore) -> Saga:
    return Saga(audit_chain=StateStoreAuditChainAdapter(store=state_store))


def raise_required_task_failure(done: set[asyncio.Task[Any]]) -> None:
    for task in done:
        if task.cancelled():
            continue
        failure = task.exception()
        if failure is None:
            continue
        _LOGGER.error(
            "required_runtime_task_failed",
            extra={"task": task.get_name()},
            exc_info=failure,
        )
        raise RuntimeError(f"required runtime task failed: {task.get_name()}") from failure


def runtime_positive_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError(f"effective runtime setting {key} is invalid")
    return value


async def start_health_server(
    *,
    control_loop: ControlLoop | None,
    startup_readiness: StartupReadinessRuntime | None,
) -> RuntimeHealthServer | None:
    raw_port = os.environ.get("FDAI_HEALTH_PORT", "").strip()
    if not raw_port:
        return None
    if control_loop is None:
        raise RuntimeError(
            "FDAI_HEALTH_PORT requires a ready control loop; set FDAI_START_CONSUMER=1"
        )
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("FDAI_HEALTH_PORT MUST be an integer") from exc
    if startup_readiness is None:
        raise RuntimeError("FDAI_HEALTH_PORT requires startup readiness composition")
    server = RuntimeHealthServer(
        port=port,
        readiness=startup_readiness.state.is_ready,
    )
    await server.start()
    _LOGGER.info("health_server_ready", extra={"port": port})
    return server


def install_shutdown_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_stop(signame: str) -> None:
        _LOGGER.info("shutdown_signal", extra={"signal": signame})
        stop.set()

    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(handled_signal, signal_stop, handled_signal.name)
    return stop


def run_main(run: Callable[[], Coroutine[Any, Any, int]]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
        force=True,
    )
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0
