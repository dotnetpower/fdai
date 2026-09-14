"""Project cloud target selectors without allowing literal objects to impersonate query evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.cloud_knowledge import Applicability

_FIELDS = {
    "cloud_provider": "provider",
    "cloud_resource_type": "resource_type",
    "cloud_generation": "service_generation",
    "cloud_skus": "skus",
    "cloud_api_versions": "api_versions",
    "cloud_regions": "regions",
    "cloud_deployment_modes": "deployment_modes",
}
_REQUIRED = frozenset({"provider", "resource_type", "service_generation"})


def cloud_target_input_schema() -> dict[str, Any]:
    """Expose bounded strings and string arrays, never evidence-valued object inputs."""
    properties = Applicability.model_json_schema()["properties"]
    return {
        argument: {
            **properties[field],
            "description": (
                f"Exact {field} selector from current-turn cloud semantic target spans. "
                "Missing conditions are unknown; this selector is not observed resource evidence."
            ),
        }
        for argument, field in _FIELDS.items()
    }


def cloud_target_arguments(target: Applicability) -> dict[str, object]:
    """Serialize an already-grounded target as scalar query constraints."""
    values = target.model_dump(mode="json")
    return {argument: values[field] for argument, field in _FIELDS.items()}


def cloud_target_from_arguments(arguments: Mapping[str, object]) -> Applicability | None:
    """Reconstruct bounded selectors; reject incomplete or object-shaped targets."""
    if "applicability" in arguments:
        raise ValueError("cloud applicability requires scalar selectors, not an object literal")
    values = {
        field: arguments[argument] for argument, field in _FIELDS.items() if argument in arguments
    }
    if not values:
        return None
    if not _REQUIRED.issubset(values):
        raise ValueError("cloud applicability requires provider, resource type, and generation")
    return Applicability.model_validate(values)
