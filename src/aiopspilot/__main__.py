"""Process entrypoint — headless control plane bootstrap.

Phase-0 smoke: load config through the composition root, wire telemetry,
emit one structured ``startup_ok`` log line with the effective config
summary (secret-free), then block on a shutdown signal. The real event
loop (Kafka consumer + trust-router + executor) lands as follow-up
wiring; this entrypoint proves the deployed image can:

- read every required env var,
- resolve the LLM bindings (local-fake or azure per :class:`LlmConfig`),
- start the OTel/logging plane,
- exit cleanly on SIGTERM (Container Apps scale-down signal).

No secrets are logged. The idempotency-key-free startup line carries
only the identifiers already stamped by the deployment (RG, tenant,
subscription short prefix) — everything customer-identifying stays out.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from .composition import default_container_from_env
from .shared.config.models import LlmMode

_LOGGER = logging.getLogger("aiopspilot.startup")


def _summarize_config(container: Any) -> dict[str, Any]:
    """Return a secret-free view of the loaded config for the startup log."""
    cfg = container.config
    return {
        "env": cfg.runtime.env,
        "autonomy_mode_default": cfg.runtime.autonomy_mode_default.value,
        "azure_region": cfg.azure.region,
        "kafka_bootstrap": cfg.kafka.bootstrap_servers,
        "kafka_topic_events": cfg.kafka.topic_events,
        "postgres_host": cfg.postgres.host,
        "postgres_db": cfg.postgres.database,
        "llm_mode": cfg.llm.mode,
        "llm_capabilities": list(cfg.llm.capabilities),
        "llm_bindings_available": container.llm_bindings is not None,
    }


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    if container.config.llm.mode == LlmMode.AZURE and container.llm_bindings is None:
        # In azure mode the entry point would normally call
        # bind_azure_llm_bindings() with a real WorkloadIdentity + httpx
        # client. That wiring is P1+ work; for now, surface the state so
        # a container-app probe sees "waiting for adapter attach".
        _LOGGER.info("azure_llm_bindings_pending_attach")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_stop(signame: str) -> None:
        _LOGGER.info("shutdown_signal", extra={"signal": signame})
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_stop, sig.name)

    await stop.wait()
    _LOGGER.info("shutdown_complete")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
    )
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    sys.exit(main())
