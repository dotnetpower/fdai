"""Production composition and entry point for the isolated Executor.

Responsibility: compose one internal shadow or authority-cutover Executor process.
Boundary: consume and publish versioned EventBus records without HTTP ingress.
Authority and state: cutover is explicit and composes the existing guarded
direct-API executor; receipts never claim independent effect verification.
Dependencies: dedicated workload identity, Event Hubs, PostgreSQL state, the
shared ResourceLock and idempotency seams, and the contract registry.
Deployment: independently runnable internal Container App process.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

from fdai_executor_service.adapters.event_hubs_kafka import (
    EventHubsKafkaBus,
    EventHubsKafkaBusConfig,
)
from fdai_executor_service.composition import (
    build_audit_store as _build_audit_store,
)
from fdai_executor_service.composition import (
    build_direct_api_effect_executor as _build_direct_api_executor,
)
from fdai_executor_service.composition import (
    build_idempotency_store as _build_idempotency_store,
)
from fdai_executor_service.composition import (
    build_resource_lock as _build_resource_lock,
)
from fdai_executor_service.composition import (
    build_workload_identity as build_runtime_workload_identity,
)
from fdai_executor_service.composition import (
    new_http_client as _new_http_client,
)
from fdai_executor_service.lifecycle import install_shutdown_signals, run_main
from fdai_executor_service.lock import (
    ExecutorShadowCommandHandler,
    LockedIsolatedExecutorShadowService,
)
from fdai_executor_service.runtime import (
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_CONSUMER_GROUP,
    EXECUTOR_RECEIPT_TOPIC,
    ExecutorCommandHandler,
    IsolatedExecutorCommandConsumer,
    IsolatedExecutorSupervisor,
)
from fdai_executor_service.service import (
    IsolatedExecutorEffectService,
    IsolatedExecutorShadowService,
)

_SHADOW_IDENTITY_ENV = "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID"
_DEPLOYED_MARKER_ENV = "FDAI_ISOLATED_EXECUTOR_DEPLOYED"
_AUTHORITY_CUTOVER_ENV = "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER"


@dataclass(frozen=True, slots=True)
class IsolatedExecutorRuntimeConfig:
    """Validated non-secret settings for one isolated Executor process."""

    bootstrap_servers: str
    command_topic: str
    receipt_topic: str
    dlq_suffix: str
    health_port: int
    executor_instance_id: str
    authority_cutover: bool

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
        authority_cutover = values.get(_AUTHORITY_CUTOVER_ENV, "").strip() == "1"
        if authority_cutover:
            _required(values, "FDAI_DEV_OPERATIONS_GATEWAY_URL")
            _required(values, "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE")
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
            authority_cutover=authority_cutover,
        )


def build_isolated_executor_supervisor(
    *,
    config: IsolatedExecutorRuntimeConfig,
    http_client: httpx.AsyncClient,
) -> IsolatedExecutorSupervisor:
    """Compose the shadow service or the explicitly gated SD-08 effect service."""

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
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    audit_store = _build_audit_store()
    idempotency = _build_idempotency_store()
    service: ExecutorCommandHandler | ExecutorShadowCommandHandler
    if config.authority_cutover:
        direct_api_executor = _build_direct_api_executor(
            audit_store=audit_store,
            resource_lock=_build_resource_lock(),
            idempotency=idempotency,
            http_client=http_client,
            identity=identity,
        )
        service = IsolatedExecutorEffectService(
            direct_api_executor=direct_api_executor,
            contract_validator=validator,
            executor_instance_id=config.executor_instance_id,
        )
    else:
        durable_service = IsolatedExecutorShadowService(
            state_store=audit_store,
            contract_validator=validator,
            executor_instance_id=config.executor_instance_id,
        )
        service = LockedIsolatedExecutorShadowService(
            delegate=durable_service,
            resource_lock=_build_resource_lock(),
        )
    consumer = IsolatedExecutorCommandConsumer(
        event_bus=event_bus,
        service=service,
        command_topic=config.command_topic,
        receipt_topic=config.receipt_topic,
        group_id=EXECUTOR_CONSUMER_GROUP,
        receipt_outbox=audit_store,
    )
    return IsolatedExecutorSupervisor(
        consumer=consumer,
        health_port=config.health_port,
        startup_checks=(audit_store.assert_schema, idempotency.assert_schema),
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
    """Run the isolated Executor until SIGTERM or SIGINT."""

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
