"""Console semantic bands must resolve against the shipped ontology release."""

from __future__ import annotations

from pathlib import Path

from fdai.delivery.ontology_console_projection import _SEMANTIC_BANDS, semantic_model_profile
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def _shipped_catalog() -> OntologyCatalog:
    return load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )


def test_every_banded_object_type_is_declared_by_the_shipped_release() -> None:
    catalog = _shipped_catalog()
    declared = {item.name for item in catalog.object_types}
    banded = {name for _, _, names in _SEMANTIC_BANDS for name in names}

    assert banded <= declared, f"bands name undeclared object types: {sorted(banded - declared)}"


def test_profile_projects_every_band_without_silent_omission() -> None:
    profile = semantic_model_profile(_shipped_catalog())

    bands = profile["bands"]
    assert isinstance(bands, list)
    projected = {band["id"]: tuple(band["object_types"]) for band in bands}
    assert projected == {identifier: names for identifier, _, names in _SEMANTIC_BANDS}
    assert profile["mutation_authority"] is False
