from __future__ import annotations

from copy import deepcopy

import pytest
from fdai.rule_catalog.schema.property_semantic import (
    PropertySemanticRegistryError,
    load_property_semantic_registry_from_mapping,
)


def _registry_mapping() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "semantics": [
            {
                "semantic_id": "utilization.cpu.p95",
                "value_type": "number",
                "canonical_unit": "percent",
                "range": {"minimum": 0, "maximum": 100},
                "normalization_rule": "number.decimal",
                "authority": {
                    "class": "provider_observed",
                    "source_identity_required": True,
                },
                "freshness": {
                    "max_age_seconds": 900,
                    "stale_behavior": "lower_autonomy",
                },
                "equivalent_provider_paths": [
                    {
                        "provider": "azure",
                        "resource_type": "compute.vm",
                        "path": "cpu_p95_percent",
                    },
                    {
                        "provider": "azure",
                        "resource_type": "compute.vm-scale-set",
                        "path": "cpu_p95_percent",
                    },
                ],
            },
            {
                "semantic_id": "security.transport.minimum_tls",
                "value_type": "string",
                "enum_values": ["tls1_2", "tls1_3"],
                "normalization_rule": "string.trim_casefold",
                "authority": {
                    "class": "provider_observed",
                    "source_identity_required": True,
                },
                "freshness": {
                    "max_age_seconds": 3600,
                    "stale_behavior": "unknown",
                },
                "equivalent_provider_paths": [
                    {
                        "provider": "azure",
                        "resource_type": "object-storage",
                        "path": "min_tls_version",
                    }
                ],
            },
            {
                "semantic_id": "lifecycle.secret.age",
                "value_type": "integer",
                "canonical_unit": "day",
                "range": {"minimum": 0},
                "normalization_rule": "integer.strict",
                "authority": {
                    "class": "derived",
                    "source_identity_required": True,
                },
                "freshness": {
                    "max_age_seconds": 86400,
                    "stale_behavior": "lower_autonomy",
                },
                "equivalent_provider_paths": [
                    {
                        "provider": "azure",
                        "resource_type": "secret-store",
                        "path": "age_days",
                    }
                ],
            },
            {
                "semantic_id": "observation.recorded_at",
                "value_type": "datetime",
                "normalization_rule": "datetime.rfc3339_utc",
                "authority": {
                    "class": "provider_observed",
                    "source_identity_required": True,
                },
                "freshness": {
                    "max_age_seconds": 300,
                    "stale_behavior": "unknown",
                },
                "equivalent_provider_paths": [
                    {
                        "provider": "azure",
                        "resource_type": "compute.vm",
                        "path": "recorded_at",
                    }
                ],
            },
        ],
    }


def test_units_range_and_numeric_normalization_are_canonical() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    semantic = registry.for_property("property.compute.vm.cpu_p95_percent")
    assert semantic is not None
    assert semantic.canonical_unit == "percent"
    assert registry.normalize("property.compute.vm.cpu_p95_percent", 20.0) == "20"
    assert registry.normalize("property.compute.vm.cpu_p95_percent", "20.500") == "20.5"

    with pytest.raises(ValueError, match="range"):
        registry.normalize("property.compute.vm.cpu_p95_percent", 100.01)


def test_enum_and_time_values_normalize_deterministically() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    assert registry.normalize("property.object-storage.min_tls_version", " TLS1_2 ") == "tls1_2"
    assert (
        registry.normalize("property.compute.vm.recorded_at", "2026-08-08T09:30:00+09:00")
        == "2026-08-08T00:30:00Z"
    )
    with pytest.raises(ValueError, match="enum"):
        registry.normalize("property.object-storage.min_tls_version", "TLS1_1")


def test_boolean_is_not_accepted_as_integer_or_number() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with pytest.raises(ValueError, match="boolean"):
        registry.normalize("property.secret-store.age_days", True)
    with pytest.raises(ValueError, match="boolean"):
        registry.normalize("property.compute.vm.cpu_p95_percent", False)


def test_duplicate_provider_path_is_rejected() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    paths = first["equivalent_provider_paths"]
    assert isinstance(paths, list)
    paths.append(deepcopy(paths[0]))

    with pytest.raises(PropertySemanticRegistryError, match="duplicate provider path"):
        load_property_semantic_registry_from_mapping(raw)


def test_equivalent_property_cannot_claim_conflicting_semantics() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    conflicting = deepcopy(semantics[1])
    assert isinstance(conflicting, dict)
    conflicting["semantic_id"] = "security.transport.protocol_floor"
    conflicting["equivalent_provider_paths"] = [
        {
            "provider": "generic",
            "resource_type": "object-storage",
            "path": "min_tls_version",
        }
    ]
    semantics.append(conflicting)

    with pytest.raises(PropertySemanticRegistryError, match="semantic conflict"):
        load_property_semantic_registry_from_mapping(raw)


def test_schema_requires_authority_and_freshness_policy() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    del first["authority"]

    with pytest.raises(PropertySemanticRegistryError, match="authority"):
        load_property_semantic_registry_from_mapping(raw)


def test_legacy_property_cannot_claim_normalized_equivalence() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    assert registry.for_property("property.compute.vm.memory_p95_percent") is None
    with pytest.raises(KeyError, match="no reviewed normalized equivalence"):
        registry.normalize("property.compute.vm.memory_p95_percent", 20)
