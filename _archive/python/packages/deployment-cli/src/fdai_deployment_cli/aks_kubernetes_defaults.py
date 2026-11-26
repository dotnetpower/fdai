"""Drop Kubernetes defaults that the API server or provider may write explicitly.

Each field is dropped only while it holds its default, so a non-default value, such as
``privileged: true``, still differs from a protected template.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

_CONTAINER_SECURITY: Mapping[str, object] = {"privileged": False, "readOnlyRootFilesystem": False}
_VOLUME_MOUNT: Mapping[str, object] = {"mountPropagation": "None"}
_KEY_REFERENCE: Mapping[str, object] = {"optional": False}
_CSI_VOLUME: Mapping[str, object] = {"fsType": ""}


def _without(value: Mapping[str, Any], defaults: Mapping[str, object]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if not (key in defaults and type(item) is type(defaults[key]) and item == defaults[key])
    }


def container_security_context(value: object) -> dict[str, Any] | None:
    """Return a copied container security context without default-valued flags."""

    return None if value is None else _without(copy.deepcopy(_mapping(value)), _CONTAINER_SECURITY)


def volume_mounts(values: Sequence[object]) -> list[dict[str, Any]]:
    """Return volume mounts without the default mount propagation."""

    return [_without(_mapping(value), _VOLUME_MOUNT) for value in values]


def environment_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return an environment entry without an empty value or key-reference ``optional: false``."""

    if "valueFrom" not in entry and entry.get("value") == "":
        # The API server omits an empty value, which Kubernetes reads as the empty string.
        del entry["value"]
    value_from = entry.get("valueFrom")
    if isinstance(value_from, dict):
        for reference in ("secretKeyRef", "configMapKeyRef"):
            if isinstance(value_from.get(reference), dict):
                value_from[reference] = _without(value_from[reference], _KEY_REFERENCE)
    return entry


def volumes(values: Sequence[object]) -> list[dict[str, Any]]:
    """Return volumes whose CSI sources omit the empty default filesystem type."""

    result = [copy.deepcopy(_mapping(value)) for value in values]
    for volume in result:
        if isinstance(volume.get("csi"), dict):
            volume["csi"] = _without(volume["csi"], _CSI_VOLUME)
    return result


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("Kubernetes object entry MUST be a mapping")
    return dict(value)
