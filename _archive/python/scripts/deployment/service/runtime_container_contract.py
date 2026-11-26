"""Normalize a primary Container App contract across Terraform and Azure shapes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

_PLANNED_PROBES = {
    "startup_probe": "startup",
    "liveness_probe": "liveness",
    "readiness_probe": "readiness",
}
_OBSERVED_PROBES = {
    "startup": "startup",
    "liveness": "liveness",
    "readiness": "readiness",
}
_PROBE_FIELD_MAP = {
    "failureThreshold": "failure_count_threshold",
    "initialDelaySeconds": "initial_delay",
    "periodSeconds": "interval_seconds",
    "successThreshold": "success_count_threshold",
    "terminationGracePeriodSeconds": "termination_grace_period_seconds",
    "timeoutSeconds": "timeout",
}
_PLANNED_OMITTED_DEFAULTS = {
    "header": [],
    "host": "",
    "initial_delay": 0,
    "path": "",
    "success_count_threshold": 1,
    "termination_grace_period_seconds": 0,
}


class RuntimeContainerContractError(ValueError):
    """Raised when a primary container cannot be reduced to a safe observable contract."""


def planned_primary_configuration(container: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Azure-observable subset of one planned primary container."""

    configuration = _common_configuration(container, observed=False)
    configuration["probes"] = _planned_probes(container)
    return configuration


def observed_primary_configuration(container: Mapping[str, Any]) -> dict[str, Any]:
    """Return one live primary container contract without provider-only defaults."""

    allowed = {
        "args",
        "command",
        "env",
        "image",
        "name",
        "probes",
        "resources",
        "volumeMounts",
    }
    if set(container) - allowed:
        raise RuntimeContainerContractError(
            "primary container has unsupported runtime configuration"
        )
    if container.get("volumeMounts") not in (None, []):
        raise RuntimeContainerContractError(
            "primary container has unsupported non-empty volume mounts"
        )
    configuration = _common_configuration(container, observed=True)
    configuration["probes"] = _observed_probes(container.get("probes"))
    return configuration


def configuration_digest(configuration: Mapping[str, Any]) -> str:
    """Return the replay-stable digest used by sealed and observed contracts."""

    encoded = (
        json.dumps(
            configuration,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def has_readiness_probe(configuration: Mapping[str, Any]) -> bool:
    """Return whether the normalized primary contract contains one readiness probe."""

    probes = configuration.get("probes")
    return isinstance(probes, Mapping) and "readiness" in probes


def _common_configuration(
    container: Mapping[str, Any],
    *,
    observed: bool,
) -> dict[str, Any]:
    name = container.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeContainerContractError("primary container name is invalid")
    configuration: dict[str, Any] = {
        "name": name,
        "command": _string_sequence(container.get("command"), "command"),
        "args": _string_sequence(container.get("args"), "args"),
        "env": _environment(container.get("env"), observed=observed),
    }
    resources = _resources(container, observed=observed)
    if resources is not None:
        configuration["resources"] = resources
    return configuration


def _string_sequence(value: object, name: str) -> list[str]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or any(not isinstance(item, str) for item in value)
    ):
        raise RuntimeContainerContractError(f"primary container {name} is invalid")
    return list(value)


def _environment(value: object, *, observed: bool) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RuntimeContainerContractError("primary container environment is invalid")
    bindings: dict[str, dict[str, str]] = {}
    secret_key = "secretRef" if observed else "secret_name"
    for item in value:
        if not isinstance(item, Mapping):
            raise RuntimeContainerContractError("primary container environment is invalid")
        name = item.get("name")
        plain = item.get("value")
        secret = item.get(secret_key)
        secret_present = isinstance(secret, str) and bool(secret)
        plain_present = isinstance(plain, str) and (bool(plain) or not secret_present)
        if (
            not isinstance(name, str)
            or not name
            or name in bindings
            or plain_present == secret_present
        ):
            raise RuntimeContainerContractError("primary container environment is invalid")
        binding = plain if plain_present else secret
        if not isinstance(binding, str):
            raise RuntimeContainerContractError("primary container environment is invalid")
        bindings[name] = {
            "name": name,
            "kind": "value" if plain_present else "secret_ref",
            "binding": binding,
        }
    return [bindings[name] for name in sorted(bindings)]


def _resources(container: Mapping[str, Any], *, observed: bool) -> dict[str, Any] | None:
    if observed:
        raw = container.get("resources")
        if raw is None:
            return None
        if (
            not isinstance(raw, Mapping)
            or not {"cpu", "memory"} <= set(raw)
            or set(raw) - {"cpu", "memory", "ephemeralStorage"}
        ):
            raise RuntimeContainerContractError("primary container resources are invalid")
        cpu = raw.get("cpu")
        memory = raw.get("memory")
    else:
        cpu = container.get("cpu")
        memory = container.get("memory")
        if cpu is None and memory is None:
            return None
    if not isinstance(cpu, (int, float)) or isinstance(cpu, bool):
        raise RuntimeContainerContractError("primary container resources are invalid")
    canonical_cpu = Decimal(str(cpu))
    if (
        not canonical_cpu.is_finite()
        or canonical_cpu <= 0
        or not isinstance(memory, str)
        or not memory
    ):
        raise RuntimeContainerContractError("primary container resources are invalid")
    normalized_cpu = canonical_cpu.normalize()
    return {
        "cpu": format(normalized_cpu, "f") if normalized_cpu else "0",
        "memory": memory,
    }


def _planned_probes(container: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    probes: dict[str, dict[str, Any]] = {}
    for source_name, canonical_name in _PLANNED_PROBES.items():
        raw = container.get(source_name)
        if raw in (None, []):
            continue
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or len(raw) != 1
            or not isinstance(raw[0], Mapping)
        ):
            raise RuntimeContainerContractError(f"primary container {source_name} is invalid")
        probe = dict(raw[0])
        for field, default in _PLANNED_OMITTED_DEFAULTS.items():
            if probe.get(field) == default:
                probe.pop(field)
        if probe.get("header") not in (None, []):
            raise RuntimeContainerContractError("primary container probe headers are unsupported")
        probe.pop("header", None)
        probes[canonical_name] = probe
    return probes


def _observed_probes(value: object) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RuntimeContainerContractError("primary container probes are invalid")
    probes: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise RuntimeContainerContractError("primary container probes are invalid")
        raw_type = item.get("type")
        if not isinstance(raw_type, str):
            raise RuntimeContainerContractError("primary container probe type is invalid")
        probe_type = _OBSERVED_PROBES.get(raw_type.casefold())
        if probe_type is None or probe_type in probes:
            raise RuntimeContainerContractError("primary container probe type is invalid")
        socket = item.get("httpGet")
        transport = "HTTP"
        if socket is None:
            socket = item.get("tcpSocket")
            transport = "TCP"
        if not isinstance(socket, Mapping):
            raise RuntimeContainerContractError("primary container probe transport is invalid")
        port = socket.get("port")
        path = socket.get("path")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65_536:
            raise RuntimeContainerContractError("primary container probe port is invalid")
        probe: dict[str, Any] = {"transport": transport, "port": port}
        if transport == "HTTP":
            if not isinstance(path, str) or not path.startswith("/"):
                raise RuntimeContainerContractError("primary container HTTP probe path is invalid")
            if socket.get("scheme") not in (None, "HTTP"):
                raise RuntimeContainerContractError(
                    "primary container HTTP probe scheme is invalid"
                )
            if socket.get("httpHeaders") not in (None, []):
                raise RuntimeContainerContractError(
                    "primary container probe headers are unsupported"
                )
            if set(socket) - {"host", "httpHeaders", "path", "port", "scheme"}:
                raise RuntimeContainerContractError(
                    "primary container HTTP probe fields are invalid"
                )
            probe["path"] = path
        elif set(socket) - {"host", "port"}:
            raise RuntimeContainerContractError("primary container TCP probe fields are invalid")
        if socket.get("host") not in (None, ""):
            raise RuntimeContainerContractError("primary container probe host is unsupported")
        allowed = {"type", "httpGet", "tcpSocket", *_PROBE_FIELD_MAP}
        if set(item) - allowed:
            raise RuntimeContainerContractError("primary container probe fields are invalid")
        for source_name, canonical_name in _PROBE_FIELD_MAP.items():
            if source_name in item:
                probe[canonical_name] = item[source_name]
        probes[probe_type] = probe
    return probes


__all__ = [
    "RuntimeContainerContractError",
    "configuration_digest",
    "has_readiness_probe",
    "observed_primary_configuration",
    "planned_primary_configuration",
]
