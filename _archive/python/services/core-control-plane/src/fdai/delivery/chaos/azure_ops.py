"""Azure chaos injector facade.

Injector families live in focused modules. This facade preserves the original
public imports and the tested ``_run`` monkeypatch hook.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdai.delivery.chaos.azure_commands import run_az, vm_run_command
from fdai.delivery.chaos.azure_data_injectors import (
    AzCosmosFailoverInjector,
    AzKeyVaultDenyAccessInjector,
    AzRedisRebootInjector,
    AzServiceBusFirewallInjector,
)
from fdai.delivery.chaos.azure_network_injectors import (
    AzCliStateProbe,
    AzLbBackendRemoveInjector,
    AzNsgRuleInjector,
)
from fdai.delivery.chaos.azure_vm_injectors import (
    AzVmLifecycleInjector,
    AzVmNetworkDisconnectInjector,
    AzVmNetworkLatencyInjector,
    AzVmPacketLossInjector,
    AzVmssLifecycleInjector,
    AzVmStopServiceInjector,
)
from fdai.delivery.chaos.live_injectors import _run  # noqa: F401 - tested compatibility hook

_RC_TIMEOUT: Final[float] = 180.0
_ARM_TIMEOUT: Final[float] = 120.0


async def _vm_run_command(
    az: str,
    resource_group: str,
    vm_name: str,
    script: str,
    *,
    timeout: float = _RC_TIMEOUT,
) -> tuple[int, str, str]:
    """Compatibility wrapper for the original guest command helper."""
    return await vm_run_command(
        az,
        resource_group,
        vm_name,
        script,
        timeout=timeout,
    )


async def _az(cmd: Sequence[str], *, timeout: float = _ARM_TIMEOUT) -> tuple[int, str, str]:
    """Compatibility wrapper for the original ARM command helper."""
    return await run_az(cmd, timeout=timeout)


__all__ = [
    "AzCliStateProbe",
    "AzCosmosFailoverInjector",
    "AzKeyVaultDenyAccessInjector",
    "AzLbBackendRemoveInjector",
    "AzNsgRuleInjector",
    "AzRedisRebootInjector",
    "AzServiceBusFirewallInjector",
    "AzVmLifecycleInjector",
    "AzVmNetworkDisconnectInjector",
    "AzVmNetworkLatencyInjector",
    "AzVmPacketLossInjector",
    "AzVmStopServiceInjector",
    "AzVmssLifecycleInjector",
    "_run",
]
