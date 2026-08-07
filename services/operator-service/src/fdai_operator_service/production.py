"""Production ASGI server lifecycle for the independent Operator process."""

from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn

from fdai_operator_service.contracts import ServerRunner
from fdai_operator_service.environment import OperatorEnvironment


def _run_uvicorn(
    factory_reference: str,
    *,
    factory: bool,
    host: str,
    port: int,
) -> object:
    """Adapt uvicorn's broad API to the service-owned server runner contract."""
    uvicorn.run(
        factory_reference,
        factory=factory,
        host=host,
        port=port,
    )
    return None


def serve(
    factory_reference: str,
    environ: Mapping[str, str] | None = None,
    *,
    runner: ServerRunner = _run_uvicorn,
) -> int:
    """Validate listener configuration and run the configured ASGI factory."""
    environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
    runner(
        factory_reference,
        factory=True,
        host=environment.host,
        port=environment.port,
    )
    return 0
