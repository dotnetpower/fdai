from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus, RuleSemanticManifest
from fdai.rule_catalog.schema.rule_semantic_surface_catalog import (
    SemanticSurfaceCatalogError,
    load_promoted_semantic_surfaces,
)
from fdai.shared.contracts.models import Redistribution

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64


def _manifest() -> RuleSemanticManifest:
    return RuleSemanticManifest(
        rule_id="rule.one",
        rule_version="1.0.0",
        corpus=RuleCorpus.ACTIVE,
        policy_ref="policies/rule.rego",
        policy_digest=_A,
        source_content_digest=_B,
        parser_id="opa-ast",
        parser_version="1.0.0",
        redistribution=Redistribution.EMBEDDABLE,
        resource_type="object-storage",
        ontology_release_digest=_A,
        signal_refs=("resource.configuration.observed",),
        property_refs=("property.object-storage.public_access",),
        action_type_ref="remediate.disable-public-access",
    )


def _surface(manifest: RuleSemanticManifest, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "surface_id": "surface.rule-one.en",
        "manifest_digest": manifest.digest,
        "locale": "en",
        "origin": "authored",
        "intent_ids": ["prevent-public-access"],
        "concept_refs": ["concept.public-access"],
        "aliases": ["block public access"],
        "training_queries": ["Which Rule blocks public storage?"],
        "hard_negative_queries": ["Which Rule enables versioning?"],
        "producer_ref": "catalog:reviewed",
        "evidence_refs": ["rule:rule.one@1.0.0"],
        "state": "promoted",
        "validation_receipt_digest": _B,
    }
    value.update(overrides)
    return value


def _write(root: Path, name: str, value: dict[str, object]) -> None:
    (root / name).write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_promoted_surface_loads_against_exact_manifest(tmp_path: Path) -> None:
    manifest = _manifest()
    _write(tmp_path, "surface.yaml", _surface(manifest))

    loaded = load_promoted_semantic_surfaces(tmp_path, manifests={manifest.rule_id: manifest})

    assert loaded[0].state.value == "promoted"
    assert loaded[0].execution_authority is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"state": "candidate"}, "promoted"),
        ({"manifest_digest": _B}, "unknown manifest"),
        ({"unexpected": True}, "Additional properties"),
    ),
)
def test_surface_catalog_rejects_unpromoted_unknown_or_extra_fields(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    manifest = _manifest()
    _write(tmp_path, "surface.yaml", _surface(manifest, **overrides))

    with pytest.raises(SemanticSurfaceCatalogError, match=message):
        load_promoted_semantic_surfaces(tmp_path, manifests={manifest.rule_id: manifest})


def test_surface_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    manifest = _manifest()
    _write(tmp_path, "left.yaml", _surface(manifest))
    _write(tmp_path, "right.yaml", _surface(manifest))

    with pytest.raises(SemanticSurfaceCatalogError, match="duplicate surface_id"):
        load_promoted_semantic_surfaces(tmp_path, manifests={manifest.rule_id: manifest})
