from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.property_semantic import (
    PropertySemanticRegistry,
    PropertySemanticRegistryError,
    load_property_semantic_registry,
    load_property_semantic_registry_from_mapping,
    property_semantic_registry_content_hash,
)


def _refresh_provenance(raw: dict[str, object]) -> None:
    raw["provenance"] = {
        "source_url": "repo://rule-catalog/vocabulary/property-semantics.yaml",
        "resolved_ref": f"property-semantics@{raw['version']}",
        "content_hash": f"sha256:{'0' * 64}",
        "license": "Apache-2.0",
        "retrieved_at": "2026-08-08T00:00:00Z",
    }
    registry = PropertySemanticRegistry.model_validate(raw)
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = property_semantic_registry_content_hash(registry)


def _registry_mapping() -> dict[str, object]:
    raw: dict[str, object] = {
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
    _refresh_provenance(raw)
    return raw


def _write_registry_with_exact_minimum(
    tmp_path: Path,
    minimum: str,
) -> tuple[Path, str]:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    range_value = first["range"]
    assert isinstance(range_value, dict)
    range_value["minimum"] = Decimal(minimum)
    _refresh_provenance(raw)
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    expected_digest = provenance["content_hash"]
    assert isinstance(expected_digest, str)

    serializable = deepcopy(raw)
    serializable_semantics = serializable["semantics"]
    assert isinstance(serializable_semantics, list)
    serializable_first = serializable_semantics[0]
    assert isinstance(serializable_first, dict)
    serializable_range = serializable_first["range"]
    assert isinstance(serializable_range, dict)
    serializable_range["minimum"] = 0
    rendered = yaml.safe_dump(serializable, sort_keys=False)
    rendered = rendered.replace("minimum: 0\n", f"minimum: {minimum}\n", 1)
    path = tmp_path / "property-semantics.yaml"
    path.write_text(rendered, encoding="utf-8")
    return path, expected_digest


def test_units_range_and_numeric_normalization_are_canonical() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    semantic = registry.for_property("property.compute.vm.cpu_p95_percent")
    assert semantic is not None
    assert semantic.canonical_unit == "percent"
    assert registry.normalize("property.compute.vm.cpu_p95_percent", 20.0) == "20"
    assert registry.normalize("property.compute.vm.cpu_p95_percent", "20.500") == "20.5"

    with pytest.raises(ValueError, match="range"):
        registry.normalize("property.compute.vm.cpu_p95_percent", 100.01)


def test_decimal_normalization_and_range_checks_ignore_ambient_context() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with localcontext() as context:
        context.prec = 4
        assert (
            registry.normalize(
                "property.compute.vm.cpu_p95_percent",
                "12.345678900",
            )
            == "12.3456789"
        )
        with pytest.raises(ValueError, match="range"):
            registry.normalize(
                "property.compute.vm.cpu_p95_percent",
                "100.0000000000000000000000001",
            )


def test_yaml_range_preserves_high_precision_and_digest(tmp_path: Path) -> None:
    minimum = "0.123456789012345678901234567890123456789"
    path, expected_digest = _write_registry_with_exact_minimum(tmp_path, minimum)

    registry = load_property_semantic_registry(path)
    semantic = registry.for_property("property.compute.vm.cpu_p95_percent")

    assert semantic is not None
    assert semantic.range is not None
    assert semantic.range.minimum == Decimal(minimum)
    assert registry.content_digest == expected_digest
    assert property_semantic_registry_content_hash(registry) == expected_digest
    assert registry.normalize("property.compute.vm.cpu_p95_percent", minimum) == minimum
    with pytest.raises(ValueError, match="below range"):
        registry.normalize(
            "property.compute.vm.cpu_p95_percent",
            "0.123456789012345678901234567890123456788",
        )


def test_equivalent_decimal_bounds_have_one_canonical_digest() -> None:
    digests: list[str] = []
    for minimum in (Decimal("1.2300"), Decimal("1.23")):
        raw = _registry_mapping()
        semantics = raw["semantics"]
        assert isinstance(semantics, list)
        first = semantics[0]
        assert isinstance(first, dict)
        range_value = first["range"]
        assert isinstance(range_value, dict)
        range_value["minimum"] = minimum
        _refresh_provenance(raw)
        registry = load_property_semantic_registry_from_mapping(raw)
        serialized = registry.model_dump(mode="json")
        serialized_semantics = serialized["semantics"]
        serialized_range = serialized_semantics[0]["range"]
        assert serialized_range["minimum"] == "1.23"
        digests.append(registry.content_digest)

    assert digests[0] == digests[1]


def test_enum_and_time_values_normalize_deterministically() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    assert registry.normalize("property.object-storage.min_tls_version", " TLS1_2 ") == "tls1_2"
    assert (
        registry.normalize("property.compute.vm.recorded_at", "2026-08-08T09:30:00+09:00")
        == "2026-08-08T00:30:00Z"
    )
    with pytest.raises(ValueError, match="enum"):
        registry.normalize("property.object-storage.min_tls_version", "TLS1_1")


@pytest.mark.parametrize(
    "value",
    (
        "2026-08-08 09:30:00+09:00",
        "2026-08-08T09:30:00",
        "2026-08-08T09:30:00.1234567Z",
    ),
)
def test_datetime_requires_strict_rfc3339(value: str) -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with pytest.raises(ValueError, match="RFC3339"):
        registry.normalize("property.compute.vm.recorded_at", value)


@pytest.mark.parametrize(
    "value",
    (
        " 2026-08-08T00:00:00Z",
        "2026-08-08T00:00:00Z ",
    ),
)
def test_datetime_rejects_surrounding_whitespace(value: str) -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with pytest.raises(ValueError, match="whitespace"):
        registry.normalize("property.compute.vm.recorded_at", value)


def test_datetime_utc_overflow_is_an_actionable_value_error() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with pytest.raises(ValueError, match="supported datetime range"):
        registry.normalize(
            "property.compute.vm.recorded_at",
            "0001-01-01T00:00:00+23:59",
        )


def test_boolean_is_not_accepted_as_integer_or_number() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    with pytest.raises(ValueError, match="boolean"):
        registry.normalize("property.secret-store.age_days", True)
    with pytest.raises(ValueError, match="boolean"):
        registry.normalize("property.compute.vm.cpu_p95_percent", False)


@pytest.mark.parametrize(
    ("value", "message"),
    (
        ("9" * 257, "coefficient"),
        ("1e1001", "exponent"),
        (("9" * 256) + "e1000", "output"),
    ),
)
def test_decimal_normalization_is_bounded(value: str, message: str) -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    del first["range"]
    _refresh_provenance(raw)
    registry = load_property_semantic_registry_from_mapping(raw)

    with pytest.raises(ValueError, match=message):
        registry.normalize("property.compute.vm.cpu_p95_percent", value)


@pytest.mark.parametrize("value_type", ("object", "array"))
def test_object_and_array_semantics_are_rejected_consistently(value_type: str) -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    first["value_type"] = value_type
    first["normalization_rule"] = "identity"

    with pytest.raises(PropertySemanticRegistryError, match="object|array|value_type"):
        load_property_semantic_registry_from_mapping(raw)


def test_units_paths_and_enum_values_are_canonical_before_conflict_checks() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    first["canonical_unit"] = " Percent "
    paths = first["equivalent_provider_paths"]
    assert isinstance(paths, list)
    duplicate = deepcopy(paths[0])
    assert isinstance(duplicate, dict)
    duplicate.update(provider=" Azure ", resource_type="COMPUTE.VM", path="CPU_P95_PERCENT")
    paths.append(duplicate)

    with pytest.raises(PropertySemanticRegistryError, match="duplicate provider path"):
        load_property_semantic_registry_from_mapping(raw)

    paths.pop()
    enum_semantic = semantics[1]
    assert isinstance(enum_semantic, dict)
    enum_semantic["enum_values"] = [" TLS1_3 ", "tls1_2", "TLS1_2"]
    _refresh_provenance(raw)
    registry = load_property_semantic_registry_from_mapping(raw)
    numeric = registry.semantics[0]
    enum = registry.semantics[1]
    assert numeric.canonical_unit == "percent"
    assert enum.enum_values == ("tls1_2", "tls1_3")


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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("source_identity_required", False, "source identity"),
        ("source_identity_required", 1, "boolean"),
        ("max_age_seconds", True, "integer"),
        ("max_age_seconds", 31_536_001, "less than or equal"),
    ),
)
def test_authority_and_freshness_are_bounded(field: str, value: object, message: str) -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    section_name = "authority" if field == "source_identity_required" else "freshness"
    section = first[section_name]
    assert isinstance(section, dict)
    section[field] = value

    with pytest.raises(PropertySemanticRegistryError, match=message):
        load_property_semantic_registry_from_mapping(raw)


def test_range_bounds_do_not_coerce_numeric_strings() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    range_value = first["range"]
    assert isinstance(range_value, dict)
    range_value["minimum"] = "0"

    with pytest.raises(PropertySemanticRegistryError, match="JSON numeric"):
        load_property_semantic_registry_from_mapping(raw)


@pytest.mark.parametrize("bound", (1.0, 1e3))
def test_integer_range_accepts_integral_finite_json_numbers(bound: float) -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    integer_semantic = semantics[2]
    assert isinstance(integer_semantic, dict)
    range_value = integer_semantic["range"]
    assert isinstance(range_value, dict)
    range_value["maximum"] = bound
    _refresh_provenance(raw)

    registry = load_property_semantic_registry_from_mapping(raw)

    loaded_range = registry.semantics[2].range
    assert loaded_range is not None
    assert loaded_range.maximum == Decimal(str(bound))


def test_integer_range_rejects_non_integral_json_number() -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    integer_semantic = semantics[2]
    assert isinstance(integer_semantic, dict)
    range_value = integer_semantic["range"]
    assert isinstance(range_value, dict)
    range_value["maximum"] = 1.5

    with pytest.raises(PropertySemanticRegistryError, match="integer range bounds"):
        load_property_semantic_registry_from_mapping(raw)


@pytest.mark.parametrize(
    ("field", "values", "message"),
    (
        ("enum_values", [str(index) for index in range(257)], "256"),
        (
            "equivalent_provider_paths",
            [
                {
                    "provider": "azure",
                    "resource_type": "compute.vm",
                    "path": f"metric_{index}",
                }
                for index in range(65)
            ],
            "64",
        ),
    ),
)
def test_pydantic_enforces_schema_collection_limits(
    field: str,
    values: list[object],
    message: str,
) -> None:
    raw = _registry_mapping()
    semantics = raw["semantics"]
    assert isinstance(semantics, list)
    first = semantics[0]
    assert isinstance(first, dict)
    first[field] = values

    with pytest.raises(PropertySemanticRegistryError, match=message):
        load_property_semantic_registry_from_mapping(raw)


def test_registry_digest_is_canonical_and_tamper_evident() -> None:
    raw = _registry_mapping()
    registry = load_property_semantic_registry_from_mapping(raw)

    assert registry.content_digest == property_semantic_registry_content_hash(registry)
    raw["version"] = "1.0.1"
    with pytest.raises(PropertySemanticRegistryError, match="content_hash mismatch"):
        load_property_semantic_registry_from_mapping(raw)


def test_legacy_property_cannot_claim_normalized_equivalence() -> None:
    registry = load_property_semantic_registry_from_mapping(_registry_mapping())

    assert registry.for_property("property.compute.vm.memory_p95_percent") is None
    with pytest.raises(KeyError, match="no reviewed normalized equivalence"):
        registry.normalize("property.compute.vm.memory_p95_percent", 20)
