"""Normalize protected sidecar configuration across Terraform and Azure ARM shapes."""

from __future__ import annotations

from typing import Any


class SidecarContractError(ValueError):
    """Raised when a sidecar cannot be reduced to the supported observable contract."""


def planned_observable_configuration(container: dict[str, Any], *, name: str) -> dict[str, Any]:
    """Return the ARM-observable subset of one reviewed Terraform sidecar."""
    if container.get("name") != name:
        raise SidecarContractError(f"sidecar {name} name changed")
    for field in ("command", "args", "env", "volume_mounts"):
        if container.get(field) not in (None, []):
            raise SidecarContractError(f"sidecar {name} has unsupported non-empty {field}")
    cpu = container.get("cpu")
    memory = container.get("memory")
    if not isinstance(cpu, (int, float)) or isinstance(cpu, bool) or not isinstance(memory, str):
        raise SidecarContractError(f"sidecar {name} resources are invalid")
    return {"name": name, "resources": {"cpu": cpu, "memory": memory}}


def observed_configuration(container: dict[str, Any], *, name: str) -> dict[str, Any]:
    """Return one live ARM sidecar contract, rejecting unsealed runtime fields."""
    allowed = {"name", "image", "probes", "resources"}
    if set(container) - allowed:
        raise SidecarContractError(f"sidecar {name} has unsupported runtime configuration")
    if container.get("name") != name:
        raise SidecarContractError(f"sidecar {name} name changed")
    resources = container.get("resources")
    if not isinstance(resources, dict) or set(resources) != {"cpu", "memory"}:
        raise SidecarContractError(f"sidecar {name} resources are invalid")
    cpu = resources.get("cpu")
    memory = resources.get("memory")
    if not isinstance(cpu, (int, float)) or isinstance(cpu, bool) or not isinstance(memory, str):
        raise SidecarContractError(f"sidecar {name} resources are invalid")
    return {"name": name, "resources": {"cpu": cpu, "memory": memory}}
