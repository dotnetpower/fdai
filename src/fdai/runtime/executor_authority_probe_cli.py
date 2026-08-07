"""One-shot governed effect probe for SD-08 cutover and rollback evidence."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC

from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.runtime.bootstrap_bindings import build_runtime_workload_identity
from fdai.runtime.bootstrap_lifecycle import run_main
from fdai.runtime.configuration import _new_http_client
from fdai.runtime.delivery import _build_direct_api_executor
from fdai.runtime.isolated_executor_client import executor_command_id
from fdai.runtime.providers import (
    _build_audit_store,
    _build_idempotency_store,
    _build_resource_lock,
)
from fdai.shared.contracts import ExecutorCommand
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)


def build_probe_action(
    *,
    operation: str,
    resource_group: str,
    nsg_name: str,
    rule_name: str,
    idempotency_key: str,
    now: datetime,
) -> Action:
    """Build one single-resource reversible NSG probe Action."""

    if operation not in {"upsert", "delete"}:
        raise ValueError("probe operation MUST be upsert or delete")
    action_type = "ops.upsert-network-rule" if operation == "upsert" else "ops.delete-network-rule"
    params: dict[str, object] = {
        "resource_group": resource_group,
        "nsg_name": nsg_name,
        "rule_name": rule_name,
    }
    if operation == "upsert":
        params["rule"] = {
            "access": "Deny",
            "direction": "Inbound",
            "protocol": "Tcp",
            "priority": 4090,
            "source_address_prefix": "192.0.2.1/32",
            "source_port_range": "*",
            "destination_address_prefix": "*",
            "destination_port_range": "65535",
        }
    return Action(
        schema_version="1.0.0",
        action_id=uuid5(NAMESPACE_URL, f"fdai:sd08-probe:action:{idempotency_key}"),
        event_id=uuid5(NAMESPACE_URL, f"fdai:sd08-probe:event:{idempotency_key}"),
        idempotency_key=idempotency_key,
        action_type=action_type,
        target_resource_ref=f"nsg:{resource_group}:{nsg_name}:{rule_name}",
        operation=Operation.UPDATE if operation == "upsert" else Operation.DELETE,
        params=params,
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3),
            ActionStopCondition(kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS, seconds=120),
        ],
        rollback_ref=RollbackRef(
            kind=RollbackKind.SCRIPTED,
            reference=(
                f"ops.delete-network-rule:{rule_name}"
                if operation == "upsert"
                else f"ops.upsert-network-rule:{rule_name}"
            ),
        ),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE,
            count=1,
            rate_per_minute=1,
        ),
        mode=Mode.ENFORCE,
        citing_rules=[action_type],
        created_at=now,
    )


async def run_probe(
    args: argparse.Namespace,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Publish remotely or execute locally, emitting one secret-free receipt."""

    values = environment or os.environ
    now = datetime.fromisoformat(args.issued_at.replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("probe issued-at MUST include a timezone")
    action = build_probe_action(
        operation=args.operation,
        resource_group=args.resource_group,
        nsg_name=args.nsg_name,
        rule_name=args.rule_name,
        idempotency_key=args.idempotency_key,
        now=now,
    )
    http_client = _new_http_client()
    try:
        identity = build_runtime_workload_identity(
            http_client,
            client_id_env="FDAI_MI_CLIENT_ID",
            require_client_id=True,
        )
        if args.transport == "local":
            executor = _build_direct_api_executor(
                audit_store=_build_audit_store(),
                resource_lock=_build_resource_lock(),
                idempotency=_build_idempotency_store(),
                http_client=http_client,
                identity=identity,
                human_access_enabled=False,
            )
            if executor is None:
                raise RuntimeError("local probe requires the in-process gateway binding")
            result = await executor.execute(action=action)
            print(
                json.dumps(
                    {
                        "action_id": str(action.action_id),
                        "idempotency_key": action.idempotency_key,
                        "outcome": result.outcome.value,
                        "transport": "local",
                    },
                    sort_keys=True,
                )
            )
            return 0 if result.outcome.value in {"dispatched", "already_applied"} else 1

        bootstrap = values.get("FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", "").strip()
        if not bootstrap:
            raise RuntimeError("isolated probe requires the auxiliary Kafka bootstrap server")
        event_bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=bootstrap,
                client_id="fdai-executor-authority-probe",
            ),
        )
        try:
            command = ExecutorCommand.from_action(
                command_id=executor_command_id(action),
                action=action,
                execution_path=ExecutionPath.DIRECT_API,
                attempt=1,
                issued_at=now,
                deadline_at=now + timedelta(minutes=2),
            )
            receipt = await event_bus.publish(
                EXECUTOR_COMMAND_TOPIC,
                command.partition_key,
                command.model_dump(mode="json"),
            )
        finally:
            await event_bus.close()
        print(
            json.dumps(
                {
                    "action_id": str(action.action_id),
                    "command_id": str(command.command_id),
                    "idempotency_key": action.idempotency_key,
                    "offset": receipt.offset,
                    "transport": "isolated",
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        await http_client.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one reversible SD-08 authority probe.")
    parser.add_argument("--transport", choices=("isolated", "local"), required=True)
    parser.add_argument("--operation", choices=("upsert", "delete"), required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--nsg-name", required=True)
    parser.add_argument("--rule-name", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--issued-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the bounded probe command."""

    args = _parser().parse_args(argv)
    return run_main(lambda: run_probe(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_probe_action", "main", "run_probe"]
