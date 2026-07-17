"""ASGI lifespan assembly for read API background services."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette

from fdai.delivery.read_api.routes import chat_registration


def build_lifespan(
    *,
    config: Any,
    live_emitter: Any,
    live_broadcaster: Any,
    agent_emitter: Any,
    agent_broadcaster: Any,
    logger: logging.Logger,
) -> Any:
    """Return the lifespan context with the established service ordering."""

    @asynccontextmanager
    async def lifespan(_app: Starlette):  # type: ignore[no-untyped-def]
        for callback in config.startup_callbacks:
            await callback()
        if live_emitter is not None:
            await live_emitter.start()
        if live_broadcaster is not None:
            await live_broadcaster.run()
        if agent_emitter is not None:
            await agent_emitter.start()
        if agent_broadcaster is not None:
            await agent_broadcaster.run()

        probe_tasks: list[Any] = []
        chat_backend = config.chat
        web_search_resolver = config.chat_web_search
        if chat_registration.is_routed_chat_backend(chat_backend):
            probe_tasks.append(
                asyncio.create_task(
                    chat_registration.periodic_latency_probe(
                        chat_backend,
                        label="CommandDeck narrator router",
                        interval_seconds=max(30, config.chat_probe_interval_seconds),
                    )
                )
            )
        if web_search_resolver is not None:
            probe_tasks.append(
                asyncio.create_task(
                    chat_registration.periodic_latency_probe(
                        web_search_resolver,
                        label="CommandDeck web-search router",
                        interval_seconds=max(
                            30,
                            int(web_search_resolver.probe_interval_seconds),
                        ),
                    )
                )
            )
        try:
            yield
        finally:
            for probe_task in probe_tasks:
                probe_task.cancel()
            if probe_tasks:
                await asyncio.gather(*probe_tasks, return_exceptions=True)
            if live_emitter is not None:
                await live_emitter.stop()
            if live_broadcaster is not None:
                await live_broadcaster.stop()
            if agent_emitter is not None:
                await agent_emitter.stop()
            if agent_broadcaster is not None:
                await agent_broadcaster.stop()
            for callback in config.shutdown_callbacks:
                try:
                    await callback()
                except Exception:  # noqa: BLE001 - shutdown is best-effort
                    logger.warning("read_api_shutdown_callback_failed", exc_info=True)

    return lifespan


__all__ = ["build_lifespan"]
