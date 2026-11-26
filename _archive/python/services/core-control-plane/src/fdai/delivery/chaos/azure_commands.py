"""Shared Azure CLI command helpers for chaos injectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

_RC_TIMEOUT: Final[float] = 180.0
_ARM_TIMEOUT: Final[float] = 120.0


async def run_az(cmd: Sequence[str], *, timeout: float = _ARM_TIMEOUT) -> tuple[int, str, str]:
    """Run one Azure CLI command through the facade compatibility hook."""
    from fdai.delivery.chaos import azure_ops

    return await azure_ops._run(cmd, timeout=timeout, drop_azure_config_dir=True)


async def vm_run_command(
    az: str,
    resource_group: str,
    vm_name: str,
    script: str,
    *,
    timeout: float = _RC_TIMEOUT,
) -> tuple[int, str, str]:
    """Invoke one guest shell script through Azure VM Run Command."""
    return await run_az(
        [
            az,
            "vm",
            "run-command",
            "invoke",
            "-g",
            resource_group,
            "-n",
            vm_name,
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            "--query",
            "value[0].message",
            "-o",
            "tsv",
        ],
        timeout=timeout,
    )
