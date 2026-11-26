"""Full-revision Entity binding and isolation, without ownership or trust enrollment."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import (
    LayerResolution,
    validate_configuration_package_for_signing,
)
from fdai_deployment_cli.lifecycle_configuration_document import (
    configuration_object,
    validate_configuration_document,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import read_object

INSTALLATION_CONFIGURATION_FORMAT = "fdai.lifecycle-configuration-package.v2"
_ENTITY_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_ENTITIES = 256


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityConfigurationInput:
    """One opaque binding with its own public overrides and private identifiers."""

    entity_id: str
    entity_overrides: Sequence[Mapping[str, object]]
    sealed_values: Mapping[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class InstallationConfigurationInput:
    """One complete customer Git revision; caller-owned selection is checked separately."""

    revision_id: str
    release_version: str
    release_digest: str
    configuration_schema: Mapping[str, object]
    environment_config: Mapping[str, object]
    sealed_values: Mapping[str, object]
    sealed_keys: frozenset[str]
    entities: Sequence[EntityConfigurationInput]


@dataclass(frozen=True, slots=True)
class InstallationLayerResolution:
    """Public configuration resolved independently for every selected Entity."""

    release_version: str
    entities: dict[str, LayerResolution]


def validate_entity_ids(entity_ids: frozenset[str]) -> None:
    """Require bounded opaque bindings, never derive identity or permission from them."""
    if not 1 <= len(entity_ids) <= _MAX_ENTITIES or any(
        not isinstance(entity_id, str) or not _ENTITY_ID.fullmatch(entity_id)
        for entity_id in entity_ids
    ):
        raise ValueError("selected Entity bindings must be bounded opaque identifiers")


def prepare_installation_configuration(
    source: InstallationConfigurationInput, *, entity_ids: frozenset[str]
) -> tuple[dict[str, object], dict[str, object]]:
    """Normalize complete inputs before signing; never discard an unknown or duplicate Entity."""
    validate_entity_ids(entity_ids)
    if not 1 <= len(source.entities) <= _MAX_ENTITIES:
        raise ValueError("configuration Entity count is invalid")
    ids = [entity.entity_id for entity in source.entities]
    if len(set(ids)) != len(ids) or frozenset(ids) != entity_ids:
        raise ValueError("configuration does not cover the exact selected Entity set")
    if not set(source.sealed_values) <= source.sealed_keys:
        raise ValueError("common sealed identifier keys are invalid")
    validate_configuration_package_for_signing(source.sealed_values)
    sealed: dict[str, object] = {}
    for entity in source.entities:
        if not set(entity.sealed_values) <= source.sealed_keys:
            raise ValueError("Entity sealed identifier keys are invalid")
        validate_configuration_package_for_signing(entity.sealed_values)
        values = {**source.sealed_values, **entity.sealed_values}
        if set(values) != source.sealed_keys:
            raise ValueError("Entity sealed identifier coverage is incomplete")
        sealed[entity.entity_id] = values
    configuration = read_object(
        canonical_bytes(
            {
                "schema": source.configuration_schema,
                "environment": source.environment_config,
                "entities": [
                    {"entity_id": entity.entity_id, "entity_overrides": entity.entity_overrides}
                    for entity in sorted(source.entities, key=lambda item: item.entity_id)
                ],
            }
        )
    )
    resolve_installation_configuration(
        configuration,
        configuration_schema=source.configuration_schema,
        release_version=source.release_version,
        sealed_keys=source.sealed_keys,
        entity_ids=entity_ids,
    )
    return configuration, read_object(canonical_bytes(sealed))


def resolve_installation_configuration(
    configuration: Mapping[str, object],
    *,
    configuration_schema: Mapping[str, object],
    release_version: str,
    sealed_keys: frozenset[str],
    entity_ids: frozenset[str],
) -> InstallationLayerResolution:
    """Require exact coverage and canonical ordering, then run the canonical layer validator."""
    validate_entity_ids(entity_ids)
    if set(configuration) != {"schema", "environment", "entities"}:
        raise ValueError("installation configuration fields are invalid")
    entries = configuration["entities"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_ENTITIES:
        raise ValueError("configuration Entities must be a bounded nonempty array")
    entities = [configuration_object(entry) for entry in entries]
    ids: list[str] = []
    resolutions: dict[str, LayerResolution] = {}
    for entity in entities:
        if set(entity) != {"entity_id", "entity_overrides"}:
            raise ValueError("Entity configuration fields are invalid")
        entity_id = entity["entity_id"]
        if not isinstance(entity_id, str) or entity_id not in entity_ids:
            raise ValueError("configuration names an unselected Entity")
        ids.append(entity_id)
        resolutions[entity_id] = validate_configuration_document(
            {
                "schema": configuration["schema"],
                "environment": configuration["environment"],
                "entity_overrides": entity["entity_overrides"],
            },
            configuration_schema,
            release_version,
            set(sealed_keys),
        )
    if ids != sorted(entity_ids):
        raise ValueError("configuration Entity coverage or ordering is invalid")
    return InstallationLayerResolution(release_version, resolutions)
