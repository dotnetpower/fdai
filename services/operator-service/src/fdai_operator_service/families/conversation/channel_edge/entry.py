"""Production server entry point for the standalone Operator channel edge."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Protocol

import uvicorn
from fdai_operator_service.families.conversation.channel_edge.environment import (
    ChannelEdgeEnvironment,
)


class ServerRunner(Protocol):
    """Run one ASGI factory on the validated listener."""

    def __call__(
        self,
        factory_reference: str,
        *,
        factory: bool,
        host: str,
        port: int,
    ) -> object: ...


def _run_uvicorn(
    factory_reference: str,
    *,
    factory: bool,
    host: str,
    port: int,
) -> object:
    uvicorn.run(factory_reference, factory=factory, host=host, port=port)
    return None


def serve(
    environ: Mapping[str, str] | None = None,
    *,
    runner: ServerRunner = _run_uvicorn,
) -> int:
    """Validate listener and dependency configuration before starting Uvicorn."""
    environment = ChannelEdgeEnvironment.parse(os.environ if environ is None else environ)
    runner(
        "fdai_operator_service.families.conversation.channel_edge.application:create_app",
        factory=True,
        host=environment.host,
        port=environment.port,
    )
    return 0


def main() -> int:
    """Serve the standalone channel edge from the process environment."""
    return serve()


__all__ = ["main", "serve"]
