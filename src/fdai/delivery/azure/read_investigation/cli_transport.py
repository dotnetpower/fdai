"""Typed Azure CLI fallback for bounded read investigations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.tools.command_catalog import CommandCatalog
from fdai.delivery.azure.read_investigation.transport import AzureRow
from fdai.shared.providers.command_runner import CommandRunner, CommandStatus
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector


class AzureReadCliError(RuntimeError):
    """The registered CLI fallback could not return a bounded projection."""


@dataclass(frozen=True, slots=True)
class AzureReadCliConfig:
    scope_ref: str
    subscription_id: str
    resource_groups: tuple[str, ...]
    resource_type_map: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (
            not self.scope_ref
            or not self.subscription_id
            or not self.resource_groups
            or len(set(self.resource_groups)) != len(self.resource_groups)
            or not self.resource_type_map
        ):
            raise ValueError("CLI read scope and resource type map MUST be configured")


class AzureCliReadTransport:
    transport_id = "cli"

    def __init__(
        self,
        *,
        config: AzureReadCliConfig,
        catalog: CommandCatalog,
        runner: CommandRunner,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._runner = runner
        self._sequence = 0
        self._neutral_by_arm = {
            arm.casefold(): neutral for arm, neutral in config.resource_type_map
        }
        self._arm_by_neutral = {neutral: arm for arm, neutral in config.resource_type_map}

    async def resolve_resources(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        self._scope(selector.scope_ref)
        groups = self._config.resource_groups
        if selector.resource_group is not None:
            matching = next(
                (
                    group
                    for group in groups
                    if group.casefold() == selector.resource_group.casefold()
                ),
                None,
            )
            if matching is None:
                raise PermissionError("requested resource group is outside the CLI scope")
            groups = (matching,)
        arguments: dict[str, object] = {"name": selector.name}
        if selector.resource_type is not None:
            arm_type = self._arm_by_neutral.get(selector.resource_type)
            if arm_type is None:
                return ()
            arguments["resource_type"] = arm_type
        values: tuple[Mapping[str, object], ...] = ()
        for resource_group in groups:
            group_values = await self._execute(
                "azure.read.resource.resolve",
                arguments={**arguments, "resource_group": resource_group},
                trusted={"subscription": self._config.subscription_id},
                limits=limits,
            )
            values = (*values, *group_values)
        output: list[AzureRow] = []
        for row in values:
            arm_type = _string(row.get("type"))
            neutral = self._neutral_by_arm.get(arm_type.casefold()) if arm_type else None
            if neutral is None:
                continue
            output.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "type": neutral,
                    "resource_group": row.get("resourceGroup"),
                }
            )
        return output[: limits.max_results + 1]

    async def get_resource_state(
        self,
        provider_ref: str,
        *,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        group, name = self._vm_parts(provider_ref)
        values = await self._execute(
            "azure.vm.status",
            arguments={"resource_group": group, "name": name},
            trusted={"subscription": self._config.subscription_id},
            limits=limits,
        )
        row = values[0] if values else {}
        statuses = row.get("statuses")
        state = "unknown"
        if isinstance(statuses, list):
            for item in statuses:
                code = item.get("code") if isinstance(item, Mapping) else None
                if isinstance(code, str) and code.startswith("PowerState/"):
                    state = code.removeprefix("PowerState/")
                    break
        return (
            {
                "observed_at": datetime.now(UTC).isoformat(),
                "status": "observed",
                "state": state,
            },
        )

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        self._vm_parts(provider_ref)
        start = datetime.now(UTC) - timedelta(seconds=lookback_seconds)
        values = await self._execute(
            "azure.activity-log.list",
            arguments={},
            trusted={
                "resource_id": provider_ref,
                "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "max_events": min(limits.max_results, 8),
                "subscription": self._config.subscription_id,
            },
            limits=limits,
        )
        return tuple(
            {
                "occurred_at": row.get("eventTimestamp"),
                "status": _nested(row, "status"),
                "operation": _nested(row, "operationName"),
                "caller": row.get("caller"),
                "caller_kind": "unknown",
                "correlation": row.get("correlationId"),
            }
            for row in values
        )

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        raise AzureReadCliError("Resource Health is unavailable through the CLI fallback")

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        raise AzureReadCliError("guest logs are unavailable through the CLI fallback")

    async def _execute(
        self,
        command_id: str,
        *,
        arguments: Mapping[str, object],
        trusted: Mapping[str, object],
        limits: ReadToolLimits,
    ) -> tuple[Mapping[str, object], ...]:
        self._sequence += 1
        digest = hashlib.sha256(
            f"{command_id}:{self._sequence}:{sorted(arguments)}".encode()
        ).hexdigest()[:24]
        plan = self._catalog.resolve(
            command_id=command_id,
            arguments=arguments,
            trusted_values=trusted,
            idempotency_key=f"read-cli:{digest}",
            dry_run=False,
        )
        receipt = await self._runner.execute(plan)
        if receipt.status is not CommandStatus.SUCCEEDED:
            raise AzureReadCliError(f"typed CLI command ended with {receipt.status.value}")
        try:
            payload = json.loads(receipt.stdout_tail)
        except json.JSONDecodeError as exc:
            raise AzureReadCliError("typed CLI command returned invalid JSON") from exc
        if isinstance(payload, Mapping):
            return (payload,)
        if not isinstance(payload, list):
            raise AzureReadCliError("typed CLI command JSON has an invalid shape")
        return tuple(row for row in payload if isinstance(row, Mapping))

    def _scope(self, scope_ref: str) -> None:
        if scope_ref != self._config.scope_ref:
            raise PermissionError("requested CLI scope is not configured")

    def _vm_parts(self, provider_ref: str) -> tuple[str, str]:
        parts = provider_ref.strip("/").split("/")
        if len(parts) != 8 or [part.casefold() for part in parts[0::2]] != [
            "subscriptions",
            "resourcegroups",
            "providers",
            "virtualmachines",
        ]:
            raise AzureReadCliError("CLI fallback supports exact VM resources only")
        if parts[1] != self._config.subscription_id:
            raise PermissionError("resolved resource is outside the configured CLI scope")
        if parts[3].casefold() not in {group.casefold() for group in self._config.resource_groups}:
            raise PermissionError("resolved resource group is outside the configured CLI scope")
        return parts[3], parts[7]


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nested(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, Mapping):
        nested = value.get("value")
        return nested if isinstance(nested, str) else None
    return value if isinstance(value, str) else None


__all__ = ["AzureCliReadTransport", "AzureReadCliConfig", "AzureReadCliError"]
