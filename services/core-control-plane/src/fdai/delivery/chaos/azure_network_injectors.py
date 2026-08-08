"""Azure network chaos injectors and read-only state probe."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai.delivery.chaos.azure_commands import run_az


class AzNsgRuleInjector:
    fault_type = "nsg_rule"

    def __init__(
        self,
        *,
        resource_group: str,
        nsg_name: str,
        rule_name: str = "fdai-chaos-deny",
        priority: int = 100,
        destination: str = "*",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._nsg = nsg_name
        self._rule = rule_name
        self._priority = int(priority)
        self._dest = destination
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        destination = str(params.get("destination", self._dest))
        rc, _out, err = await run_az(
            [
                self._az,
                "network",
                "nsg",
                "rule",
                "create",
                "-g",
                self._rg,
                "--nsg-name",
                self._nsg,
                "-n",
                self._rule,
                "--priority",
                str(self._priority),
                "--access",
                "Deny",
                "--direction",
                "Outbound",
                "--protocol",
                "*",
                "--destination-address-prefixes",
                destination,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az network nsg rule create failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await run_az(
            [
                self._az,
                "network",
                "nsg",
                "rule",
                "delete",
                "-g",
                self._rg,
                "--nsg-name",
                self._nsg,
                "-n",
                self._rule,
            ]
        )


class AzLbBackendRemoveInjector:
    fault_type = "lb_backend_remove"

    def __init__(
        self,
        *,
        resource_group: str,
        lb_name: str,
        pool_name: str,
        address_name: str,
        address_ip: str | None = None,
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._lb = lb_name
        self._pool = pool_name
        self._addr = address_name
        self._addr_ip = address_ip
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await run_az(
            [
                self._az,
                "network",
                "lb",
                "address-pool",
                "address",
                "remove",
                "-g",
                self._rg,
                "--lb-name",
                self._lb,
                "--pool-name",
                self._pool,
                "-n",
                self._addr,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az network lb address remove failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        if not self._addr_ip:
            return
        await run_az(
            [
                self._az,
                "network",
                "lb",
                "address-pool",
                "address",
                "add",
                "-g",
                self._rg,
                "--lb-name",
                self._lb,
                "--pool-name",
                self._pool,
                "-n",
                self._addr,
                "--ip-address",
                self._addr_ip,
            ]
        )


class AzCliStateProbe:
    """Observe injected state through one read-only Azure CLI command."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        expected_substrings: Sequence[str] = (),
        absent_substrings: Sequence[str] = (),
    ) -> None:
        if not command:
            raise ValueError("command MUST be non-empty")
        if not expected_substrings and not absent_substrings:
            raise ValueError("at least one expected or absent substring is required")
        self._command = tuple(command)
        self._expected = tuple(expected_substrings)
        self._absent = tuple(absent_substrings)

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await run_az(self._command)
        if rc != 0:
            return False
        return all(value in out for value in self._expected) and all(
            value not in out for value in self._absent
        )
