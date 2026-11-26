"""Catalog contract tests for Pod telemetry relationship coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.link_type import (
    LinkTypeCatalogError,
    load_link_type_from_mapping,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_observation_target_link_loads_with_valid_provenance_and_endpoints() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )

    link = next(item for item in catalog.link_types if item.name == "observation_targets_resource")
    assert link.from_type == "Observation"
    assert link.to_type == "Resource"


@pytest.mark.parametrize(
    ("field_name", "invalid_type", "message"),
    (
        ("from_type", "MissingObservationType", "unknown from_type"),
        ("to_type", "MissingResourceType", "unknown to_type"),
    ),
)
def test_observation_target_link_rejects_unknown_endpoint_type(
    field_name: str,
    invalid_type: str,
    message: str,
) -> None:
    path = REPO_ROOT / "rule-catalog/vocabulary/link-types/observation_targets_resource.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw[field_name] = invalid_type

    with pytest.raises(LinkTypeCatalogError, match=message):
        load_link_type_from_mapping(
            raw,
            schema_registry=PackageResourceSchemaRegistry(),
            object_type_names={"Observation", "Resource"},
            origin=path.name,
        )
