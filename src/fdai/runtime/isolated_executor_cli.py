"""Production composition and entry point for the isolated Executor.

Responsibility: compose one internal shadow-only Executor process.
Boundary: consume and publish versioned EventBus records without HTTP ingress.
Authority and state: durable no-effect receipts only; no provider effect adapter
or mutation-capable identity is accepted before SD-08.
Dependencies: dedicated shadow workload identity, Event Hubs, PostgreSQL state,
the shared ResourceLock seam, and the contract registry.
Deployment: independently runnable internal Container App process.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.runtime.bootstrap_bindings import build_runtime_workload_identity
from fdai.runtime.bootstrap_lifecycle import install_shutdown_signals, run_main
from fdai.runtime.configuration import _new_http_client
from fdai.runtime.isolated_executor import IsolatedExecutorShadowService
from fdai.runtime.isolated_executor_lock import LockedIsolatedExecutorShadowService
from fdai.runtime.isolated_executor_runtime import (
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_CONSUMER_GROUP,
    EXECUTOR_RECEIPT_TOPIC,
    IsolatedExecutorCommandConsumer,
    IsolatedExecutorSupervisor,
)
from fdai.runtime.providers import _build_audit_store, _build_resource_lock
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator

_SHADOW_IDENTITY_ENV = "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID"
_DEPLOYED_MARKER_ENV = "FDAI_ISOLATED_EXECUTOR_DEPLOYED"


@dataclass(frozen=True, slots=True)
class IsolatedExecutorRuntimeConfig:
    """Validated non-secret settings for one isolated Executor process."""

    bootstrap_servers: str
    command_topic: str
    receipt_topic: str
    dlq_suffix: str
    health_port: int
    executor_instance_id: str

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> IsolatedExecutorRuntimeConfig:
        """Load a durable, dedicated-identity shadow configuration."""

        values = environment or os.environ
        _required(values, "RUNTIME_ENV")
        if values.get(_DEPLOYED_MARKER_ENV, "").strip() != "1":
            raise RuntimeError(
                f"{_DEPLOYED_MARKER_ENV}=1 MUST select the deployed isolated Executor"
            )
        bootstrap_servers = _required(values, "KAFKA_BOOTSTRAP_SERVERS")
        _required(values, "FDAI_STATE_STORE_DSN")
        _required(values, _SHADOW_IDENTITY_ENV)
        command_topic = values.get(
            "FDAI_EXECUTOR_COMMAND_TOPIC",
            EXECUTOR_COMMAND_TOPIC,
        ).strip()
        receipt_topic = values.get(
            "FDAI_EXECUTOR_RECEIPT_TOPIC",
            EXECUTOR_RECEIPT_TOPIC,
        ).strip()
        if not command_topic or not receipt_topic or command_topic == receipt_topic:
            raise RuntimeError("isolated Executor command and receipt topics MUST be distinct")
        dlq_suffix = values.get("KAFKA_TOPIC_DLQ_SUFFIX", ".dlq").strip()
        if not dlq_suffix:
            raise RuntimeError("KAFKA_TOPIC_DLQ_SUFFIX MUST NOT be empty")
        raw_port = values.get("FDAI_ISOLATED_EXECUTOR_HEALTH_PORT", "8000").strip()
        try:
            health_port = int(raw_port)
        except ValueError as exc:
            raise RuntimeError("FDAI_ISOLATED_EXECUTOR_HEALTH_PORT MUST be an integer") from exc
        if not 1 <= health_port <= 65_535:
            raise RuntimeError("FDAI_ISOLATED_EXECUTOR_HEALTH_PORT MUST be between 1 and 65535")
        instance_id = values.get("FDAI_ISOLATED_EXECUTOR_INSTANCE_ID", "").strip()
        if not instance_id:
            instance_id = values.get("HOSTNAME", "").strip() or socket.gethostname()
        if not instance_id or len(instance_id) > 512:
            raise RuntimeError("isolated Executor instance id MUST be bounded and non-empty")
        return cls(
            bootstrap_servers=bootstrap_servers,
            command_topic=command_topic,
            receipt_topic=receipt_topic,
            dlq_suffix=dlq_suffix,
            health_port=health_port,
            executor_instance_id=instance_id,
        )


def build_isolated_executor_supervisor(
    *,
    config: IsolatedExecutorRuntimeConfig,
    http_client: httpx.AsyncClient,
) -> IsolatedExecutorSupervisor:
    """Compose the shadow service without any provider effect binding."""

    identity = build_runtime_workload_identity(
        http_client,
        client_id_env=_SHADOW_IDENTITY_ENV,
        require_client_id=True,
    )
    event_bus = EventHubsKafkaBus(
        identity=identity,
        config=EventHubsKafkaBusConfig(
            bootstrap_servers=config.bootstrap_servers,
            client_id="fdai-isolated-executor-shadow",
            dlq_suffix=config.dlq_suffix,
            auto_offset_reset="earliest",
        ),
    )
    durable_service = IsolatedExecutorShadowService(
        state_store=_build_audit_store(),
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id=config.executor_instance_id,
    )
    locked_service = LockedIsolatedExecutorShadowService(
        delegate=durable_service,
        resource_lock=_build_resource_lock(),
    )
    consumer = IsolatedExecutorCommandConsumer(
        event_bus=event_bus,
        service=locked_service,
        command_topic=config.command_topic,
        receipt_topic=config.receipt_topic,
        group_id=EXECUTOR_CONSUMER_GROUP,
    )
    return IsolatedExecutorSupervisor(
        consumer=consumer,
        health_port=config.health_port,
        shutdown_callbacks=(event_bus.close, http_client.aclose),
    )


async def _run() -> int:
    config = IsolatedExecutorRuntimeConfig.from_env()
    http_client = _new_http_client()
    try:
        supervisor = build_isolated_executor_supervisor(
            config=config,
            http_client=http_client,
        )
    except BaseException:
        await http_client.aclose()
        raise
    return await supervisor.run(stop=install_shutdown_signals())


def main() -> int:
    """Run the isolated shadow Executor until SIGTERM or SIGINT."""

    return run_main(_run)


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} MUST be configured for the isolated Executor")
    return value


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "IsolatedExecutorRuntimeConfig",
    "build_isolated_executor_supervisor",
    "main",
]
