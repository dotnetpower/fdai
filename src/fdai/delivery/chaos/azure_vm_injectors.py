"""Azure guest-OS and VM lifecycle chaos injectors."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.chaos.azure_commands import run_az, vm_run_command


class AzVmNetworkLatencyInjector:
    fault_type = "network_delay"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        latency_ms: int = 250,
        interface: str = "eth0",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._latency = int(latency_ms)
        self._iface = interface
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        latency = int(params.get("latency_ms", self._latency))
        iface = str(params.get("interface", self._iface))
        script = (
            f"tc qdisc del dev {iface} root 2>/dev/null; "
            f"tc qdisc add dev {iface} root netem delay {latency}ms && echo added"
        )
        rc, _out, err = await vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"az vm run-command tc netem delay failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"tc qdisc del dev {self._iface} root 2>/dev/null; echo cleared"
        await vm_run_command(self._az, self._rg, self._vm, script)


class AzVmPacketLossInjector:
    fault_type = "network_loss"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        loss_percent: int = 20,
        interface: str = "eth0",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._loss = int(loss_percent)
        self._iface = interface
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        loss = int(params.get("loss_percent", self._loss))
        iface = str(params.get("interface", self._iface))
        script = (
            f"tc qdisc del dev {iface} root 2>/dev/null; "
            f"tc qdisc add dev {iface} root netem loss {loss}% && echo added"
        )
        rc, _out, err = await vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"az vm run-command tc netem loss failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"tc qdisc del dev {self._iface} root 2>/dev/null; echo cleared"
        await vm_run_command(self._az, self._rg, self._vm, script)


class AzVmNetworkDisconnectInjector:
    fault_type = "network_disconnect"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        destination: str,
        az: str = "az",
    ) -> None:
        if not destination:
            raise ValueError("destination MUST be non-empty (host or CIDR)")
        self._rg = resource_group
        self._vm = vm_name
        self._dest = destination
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        dest = str(params.get("destination", self._dest))
        script = f"iptables -I OUTPUT -d {dest} -j DROP && echo blocked"
        rc, _out, err = await vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"iptables DROP add failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"iptables -D OUTPUT -d {self._dest} -j DROP 2>/dev/null; echo cleared"
        await vm_run_command(self._az, self._rg, self._vm, script)


class AzVmStopServiceInjector:
    fault_type = "stop_service"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        service: str,
        az: str = "az",
    ) -> None:
        if not service:
            raise ValueError("service MUST be non-empty")
        self._rg = resource_group
        self._vm = vm_name
        self._svc = service
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        service = str(params.get("service", self._svc))
        script = f"systemctl stop {service} && echo stopped"
        rc, _out, err = await vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"systemctl stop {service} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"systemctl start {self._svc}; echo started"
        await vm_run_command(self._az, self._rg, self._vm, script)


class AzVmLifecycleInjector:
    fault_type = "vm_lifecycle"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        action: str = "deallocate",
        az: str = "az",
    ) -> None:
        if action not in {"deallocate", "restart", "redeploy"}:
            raise ValueError(f"unknown VM lifecycle action {action!r}")
        self._rg = resource_group
        self._vm = vm_name
        self._action = action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        action = str(params.get("action", self._action))
        rc, _out, err = await run_az([self._az, "vm", action, "-g", self._rg, "-n", self._vm])
        if rc != 0:
            raise RuntimeError(f"az vm {action} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        if self._action == "restart":
            return
        await run_az([self._az, "vm", "start", "-g", self._rg, "-n", self._vm])


class AzVmssLifecycleInjector:
    fault_type = "vmss_lifecycle"

    def __init__(
        self,
        *,
        resource_group: str,
        vmss_name: str,
        action: str = "deallocate",
        az: str = "az",
    ) -> None:
        if action not in {"deallocate", "restart"}:
            raise ValueError(f"unknown VMSS lifecycle action {action!r}")
        self._rg = resource_group
        self._vmss = vmss_name
        self._action = action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        action = str(params.get("action", self._action))
        rc, _out, err = await run_az([self._az, "vmss", action, "-g", self._rg, "-n", self._vmss])
        if rc != 0:
            raise RuntimeError(f"az vmss {action} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        if self._action == "restart":
            return
        await run_az([self._az, "vmss", "start", "-g", self._rg, "-n", self._vmss])
