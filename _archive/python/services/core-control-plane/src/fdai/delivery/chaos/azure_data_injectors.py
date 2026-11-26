"""Azure data-service chaos injectors."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.chaos.azure_commands import run_az


class AzRedisRebootInjector:
    fault_type = "redis_reboot"

    def __init__(
        self,
        *,
        resource_group: str,
        cache_name: str,
        reboot_type: str = "AllNodes",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._cache = cache_name
        self._reboot_type = reboot_type
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        reboot_type = str(params.get("reboot_type", self._reboot_type))
        rc, _out, err = await run_az(
            [
                self._az,
                "redis",
                "force-reboot",
                "-g",
                self._rg,
                "-n",
                self._cache,
                "--reboot-type",
                reboot_type,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az redis force-reboot failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        return None


class AzCosmosFailoverInjector:
    fault_type = "cosmosdb_failover"

    def __init__(
        self,
        *,
        resource_group: str,
        account_name: str,
        original_priorities: str,
        failover_priorities: str,
        az: str = "az",
    ) -> None:
        if not original_priorities or not failover_priorities:
            raise ValueError("original_priorities and failover_priorities MUST be non-empty")
        self._rg = resource_group
        self._account = account_name
        self._original = original_priorities
        self._failover = failover_priorities
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        priorities = str(params.get("failover_priorities", self._failover))
        rc, _out, err = await run_az(
            [
                self._az,
                "cosmosdb",
                "failover-priority-change",
                "-g",
                self._rg,
                "-n",
                self._account,
                "--failover-policies",
                priorities,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az cosmosdb failover-priority-change failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await run_az(
            [
                self._az,
                "cosmosdb",
                "failover-priority-change",
                "-g",
                self._rg,
                "-n",
                self._account,
                "--failover-policies",
                self._original,
            ]
        )


class AzKeyVaultDenyAccessInjector:
    fault_type = "keyvault_deny_access"

    def __init__(
        self,
        *,
        resource_group: str,
        vault_name: str,
        original_default_action: str = "Allow",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vault = vault_name
        self._original = original_default_action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await run_az(
            [
                self._az,
                "keyvault",
                "network-rule",
                "add",
                "--name",
                self._vault,
                "-g",
                self._rg,
                "--default-action",
                "Deny",
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az keyvault network-rule set Deny failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await run_az(
            [
                self._az,
                "keyvault",
                "update",
                "--name",
                self._vault,
                "-g",
                self._rg,
                "--default-action",
                self._original,
            ]
        )


class AzServiceBusFirewallInjector:
    fault_type = "servicebus_firewall"

    def __init__(
        self,
        *,
        resource_group: str,
        namespace_name: str,
        original_default_action: str = "Allow",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._ns = namespace_name
        self._original = original_default_action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await run_az(
            [
                self._az,
                "servicebus",
                "namespace",
                "network-rule-set",
                "update",
                "-g",
                self._rg,
                "--namespace-name",
                self._ns,
                "--default-action",
                "Deny",
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az servicebus network-rule-set Deny failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await run_az(
            [
                self._az,
                "servicebus",
                "namespace",
                "network-rule-set",
                "update",
                "-g",
                self._rg,
                "--namespace-name",
                self._ns,
                "--default-action",
                self._original,
            ]
        )
