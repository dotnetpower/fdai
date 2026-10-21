"""Shared complete-document validation for single and multi-Entity packages."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import (
    LayerResolution,
    resolve_configuration_layers,
    validate_configuration_package_for_signing,
    validate_release_configuration_schema,
)


def configuration_object(value: object) -> dict[str, object]:
    """Require an object without coercing untrusted keys."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("configuration field must be an object")
    return {str(key): item for key, item in value.items()}


def validate_configuration_document(
    configuration: Mapping[str, object],
    schema: Mapping[str, object],
    release_version: str,
    sealed_keys: set[str],
) -> LayerResolution:
    """Validate every layer, including unused overrides, before resolving one Entity."""
    if set(configuration) != {"schema", "environment", "entity_overrides"}:
        raise ValueError("configuration document fields are invalid")
    if canonical_bytes(configuration["schema"]) != canonical_bytes(schema):
        raise ValueError("configuration schema does not match the trusted Release schema")
    validate_release_configuration_schema(schema)
    defaults = {
        key: entry["default"]
        for key, raw_entry in schema.items()
        if "default" in (entry := configuration_object(raw_entry))
    }
    validate_configuration_package_for_signing(
        {
            "defaults": defaults,
            "environment": configuration["environment"],
            "entity_overrides": configuration["entity_overrides"],
        }
    )
    overrides = configuration["entity_overrides"]
    if not isinstance(overrides, list | tuple):
        raise ValueError("configuration overrides must be a sequence")
    blocks = [configuration_object(item) for item in overrides]
    for block in blocks:
        if set(block) != {"versions", "values"}:
            raise ValueError("configuration override fields are invalid")
        _reject_public_identifiers(block["values"], sealed_keys)
    _reject_public_identifiers(defaults, sealed_keys)
    _reject_public_identifiers(configuration["environment"], sealed_keys)
    return resolve_configuration_layers(
        release_version=release_version,
        configuration_schema=schema,
        environment_config=configuration_object(configuration["environment"]),
        entity_overrides=blocks,
        sealed_keys=sealed_keys,
    )


def _reject_public_identifiers(value: object, sealed_keys: set[str]) -> None:
    if isinstance(value, Mapping):
        if sealed_keys.intersection(value):
            raise ValueError("sealed identifier belongs in the sealed section")
        for item in value.values():
            _reject_public_identifiers(item, sealed_keys)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_public_identifiers(item, sealed_keys)
