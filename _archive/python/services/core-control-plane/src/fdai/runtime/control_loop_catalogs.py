"""Catalog loaders used by active control-loop composition."""

from __future__ import annotations

from pathlib import Path

import yaml

from fdai.rule_catalog.schema.parameter_relaxation_policy import (
    ParameterRelaxationPolicy,
    parameter_relaxation_policies_from_mapping,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.runtime.configuration import _resolve_catalog_root


def load_resource_types() -> ResourceTypeRegistry:
    vocabulary_file = _resolve_catalog_root() / "vocabulary" / "resource-types.yaml"
    with vocabulary_file.open("r", encoding="utf-8") as handle:
        return load_resource_type_registry_from_mapping(yaml.safe_load(handle))


def load_parameter_relaxation_policies(
    catalog_root: Path,
) -> dict[str, ParameterRelaxationPolicy]:
    """Load separately reviewed override parameter-relaxation bounds."""

    policy_file = catalog_root / "override-parameter-bounds.yaml"
    if not policy_file.is_file():
        return {}
    with policy_file.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return parameter_relaxation_policies_from_mapping(raw)


__all__ = ["load_parameter_relaxation_policies", "load_resource_types"]
