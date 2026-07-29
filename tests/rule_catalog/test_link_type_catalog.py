"""Ontology LinkType catalog loader tests.

Covers:
- The shipped LinkTypes load cleanly when the built-in ObjectType
  catalog is provided.
- Missing ObjectType endpoints (typo in `from_type` / `to_type`)
  fail-close with an aggregated error.
- Duplicate `name` across files fails-close.
- The transitive / temporal_order flags round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.rule_catalog.schema.link_type import (
    LinkTypeCatalogError,
    link_type_names,
    load_link_type_catalog,
    load_link_type_from_mapping,
)
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
OBJECT_TYPE_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_TYPE_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _object_types() -> tuple:
    return load_object_type_catalog(OBJECT_TYPE_ROOT, schema_registry=_registry())


def test_shipped_link_types_load() -> None:
    catalog = load_link_type_catalog(
        LINK_TYPE_ROOT,
        schema_registry=_registry(),
        object_types=_object_types(),
    )
    names = link_type_names(catalog)
    assert names >= {
        "applies_to",
        "triggered_by",
        "evaluates",
        "remediates",
        "resource_of",
        "contains",
        "attached_to",
        "depends_on",
        "precedes",
        # Process automation (docs/roadmap/decisioning/process-automation.md 3.2)
        "targets",
        "advances",
    }
    by_name = {link.name: link for link in catalog}
    assert by_name["applies_to"].to_type == "ResourceType"
    assert by_name["triggered_by"].to_type == "SignalType"
    assert by_name["evaluates"].to_type == "Property"
    assert by_name["remediates"].to_type == "ActionType"


def test_transitive_flag_round_trips() -> None:
    catalog = load_link_type_catalog(
        LINK_TYPE_ROOT,
        schema_registry=_registry(),
        object_types=_object_types(),
    )
    by_name = {link.name: link for link in catalog}
    assert by_name["contains"].is_transitive is True
    # attached_to is deliberately non-transitive; regression guard.
    assert by_name["attached_to"].is_transitive is False


def test_temporal_order_flag_round_trips() -> None:
    catalog = load_link_type_catalog(
        LINK_TYPE_ROOT,
        schema_registry=_registry(),
        object_types=_object_types(),
    )
    by_name = {link.name: link for link in catalog}
    assert by_name["precedes"].temporal_order is True
    assert by_name["precedes"].order_by_property == "evaluation_ts"


def test_temporal_order_property_must_resolve_on_target() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "ordered_findings",
        "version": "1.0.0",
        "from_type": "Finding",
        "to_type": "Finding",
        "cardinality": "many_to_many",
        "temporal_order": True,
        "order_by_property": "missing_timestamp",
    }
    object_types = _object_types()
    by_name = {item.name: item for item in object_types}
    with pytest.raises(LinkTypeCatalogError, match="missing_timestamp"):
        load_link_type_from_mapping(
            raw,
            schema_registry=_registry(),
            object_type_names=set(by_name),
            object_types_by_name=by_name,
        )


def test_unknown_from_type_fails() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "bogus_link",
        "version": "1.0.0",
        "from_type": "NotARealObjectType",
        "to_type": "Resource",
        "cardinality": "many_to_many",
    }
    with pytest.raises(LinkTypeCatalogError) as info:
        load_link_type_from_mapping(
            raw,
            schema_registry=_registry(),
            object_type_names={"Resource", "Rule"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown from_type" in joined
    assert "notarealobjecttype" in joined


def test_unknown_to_type_fails() -> None:
    raw = {
        "schema_version": "1.0.0",
        "name": "bogus_link",
        "version": "1.0.0",
        "from_type": "Resource",
        "to_type": "NotARealObjectType",
        "cardinality": "many_to_many",
    }
    with pytest.raises(LinkTypeCatalogError) as info:
        load_link_type_from_mapping(
            raw,
            schema_registry=_registry(),
            object_type_names={"Resource", "Rule"},
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "unknown to_type" in joined


def test_duplicate_name_across_files_fails(tmp_path: Path) -> None:
    body = (
        'schema_version: "1.0.0"\n'
        "name: dupe_link\n"
        'version: "1.0.0"\n'
        "from_type: Resource\n"
        "to_type: Resource\n"
        "cardinality: many_to_many\n"
    )
    (tmp_path / "one.yaml").write_text(body)
    (tmp_path / "two.yaml").write_text(body)
    with pytest.raises(LinkTypeCatalogError) as info:
        load_link_type_catalog(
            tmp_path,
            schema_registry=_registry(),
            object_types=_object_types(),
        )
    joined = " ".join(i.message for i in info.value.issues).lower()
    assert "duplicate linktype name 'dupe_link'" in joined


def test_invalid_name_pattern_fails(tmp_path: Path) -> None:
    # Name MUST be snake_case starting with a lowercase letter.
    (tmp_path / "bad.yaml").write_text(
        'schema_version: "1.0.0"\n'
        "name: BadCamelCase\n"
        'version: "1.0.0"\n'
        "from_type: Resource\n"
        "to_type: Resource\n"
        "cardinality: many_to_many\n"
    )
    with pytest.raises(LinkTypeCatalogError) as info:
        load_link_type_catalog(
            tmp_path,
            schema_registry=_registry(),
            object_types=_object_types(),
        )
    keys = " ".join(i.key for i in info.value.issues)
    assert "bad.yaml:name" in keys
