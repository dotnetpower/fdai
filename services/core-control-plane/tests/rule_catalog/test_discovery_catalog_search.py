from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.catalog_search import (
    build_discovery_catalog_search_documents,
    catalog_search_document_digest,
)
from fdai.rule_catalog.schema.discovery_rule import load_discovery_rule_catalog
from fdai.rule_catalog.schema.rule import RuleCatalogError
from fdai.rule_catalog.schema.rule_semantic_generation import build_document_digest_manifest
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
DISCOVERY_ROOT = REPO_ROOT / "rule-catalog" / "collected"


def test_complete_discovery_corpus_materializes_with_replayable_identity() -> None:
    rules = load_discovery_rule_catalog(
        DISCOVERY_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
    )
    documents = build_discovery_catalog_search_documents(rules)
    document_digests = tuple(catalog_search_document_digest(item) for item in documents)
    manifest = build_document_digest_manifest(document_digests)

    assert len(rules) == 8_487
    assert len(documents) == len(rules)
    assert tuple(item.rule_id for item in documents) == tuple(sorted(rule.id for rule in rules))
    assert all(item.corpus == "discovery" for item in documents)
    assert manifest.document_count == 8_487
    assert len(manifest.chunks) == 34
    assert sum(chunk.document_count for chunk in manifest.chunks) == 8_487

    repeated = build_discovery_catalog_search_documents(rules)
    repeated_digests = tuple(catalog_search_document_digest(item) for item in repeated)
    assert build_document_digest_manifest(repeated_digests) == manifest


def test_discovery_loader_rejects_empty_catalog(tmp_path: Path) -> None:
    with pytest.raises(RuleCatalogError, match="contains no Rule YAML files"):
        load_discovery_rule_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )


def test_discovery_loader_rejects_invalid_and_duplicate_records(tmp_path: Path) -> None:
    raw = yaml.safe_load(next(DISCOVERY_ROOT.rglob("*.yaml")).read_text(encoding="utf-8"))
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "duplicate.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "invalid.yaml").write_text("schema_version: 1.0.0\n", encoding="utf-8")

    with pytest.raises(RuleCatalogError) as raised:
        load_discovery_rule_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )

    assert any("duplicate rule id" in issue.message for issue in raised.value.issues)
    assert any(issue.key.startswith("invalid.yaml:") for issue in raised.value.issues)
