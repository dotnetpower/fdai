from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.rule_catalog.schema.catalog_search import (
    build_catalog_search_documents,
    build_discovery_catalog_search_documents,
    catalog_search_document_digest,
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.discovery_rule import load_discovery_rule_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import RuleCatalogError, load_rule_catalog
from fdai.rule_catalog.schema.rule_semantic_generation import build_document_digest_manifest
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
RULE_CATALOG_ROOT = REPO_ROOT / "rule-catalog"
DISCOVERY_ROOT = REPO_ROOT / "rule-catalog" / "collected"
NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _generation_metadata(
    *,
    corpus: CatalogCorpus,
    catalog_digest: str,
    ontology_release_digest: str,
    documents: tuple[CatalogSearchDocument, ...],
) -> CatalogGenerationMetadata:
    document_digests = tuple(catalog_search_document_digest(item) for item in documents)
    manifest = build_document_digest_manifest(document_digests)
    generation_digest = _digest(
        "\0".join(
            (
                corpus,
                catalog_digest,
                ontology_release_digest,
                manifest.document_digest_root,
            )
        )
    )
    return CatalogGenerationMetadata(
        generation_id=f"rule-search:{corpus}:{generation_digest[7:31]}",
        generation_digest=generation_digest,
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="lexical-only-v1",
        embedding_model_version="lexical-only-v1",
        embedding_dimension=1,
        validation_receipt_digest=_digest(f"validated\0{generation_digest}"),
    )


def _load_active_corpus() -> tuple[
    tuple[CatalogSearchDocument, ...],
    CatalogGenerationMetadata,
]:
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        RULE_CATALOG_ROOT,
        schema_registry=registry,
        probes_root=RULE_CATALOG_ROOT / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (RULE_CATALOG_ROOT / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        RULE_CATALOG_ROOT / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=RULE_CATALOG_ROOT / "remediation",
    )
    policy_semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in rules
    }
    documents = build_catalog_search_documents(
        rules=rules,
        action_types=ontology.action_types,
        policy_semantics=policy_semantics,
    )
    return documents, _generation_metadata(
        corpus="active",
        catalog_digest=rule_reference_catalog_digest(rules),
        ontology_release_digest=ontology.build_release().digest,
        documents=documents,
    )


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


async def test_real_active_and_discovery_corpora_have_isolated_lifecycles() -> None:
    active_documents, active_metadata = _load_active_corpus()
    discovery_rules = load_discovery_rule_catalog(
        DISCOVERY_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
    )
    discovery_documents = build_discovery_catalog_search_documents(discovery_rules)
    discovery_first = _generation_metadata(
        corpus="discovery",
        catalog_digest=rule_reference_catalog_digest(discovery_rules),
        ontology_release_digest=active_metadata.ontology_release_digest,
        documents=discovery_documents,
    )
    changed_discovery_documents = (
        replace(discovery_documents[0], text=f"{discovery_documents[0].text}\ncandidate-refresh"),
        *discovery_documents[1:],
    )
    discovery_second = _generation_metadata(
        corpus="discovery",
        catalog_digest=discovery_first.catalog_digest,
        ontology_release_digest=active_metadata.ontology_release_digest,
        documents=changed_discovery_documents,
    )
    index = InMemoryCatalogSemanticIndex()

    assert await index.stage_generation(active_metadata, active_documents) == 62
    assert await index.stage_generation(discovery_first, discovery_documents) == 8_487
    assert await index.active_generation("active") is None
    assert await index.active_generation("discovery") is None
    staged_generations: tuple[tuple[CatalogCorpus, CatalogGenerationMetadata], ...] = (
        ("active", active_metadata),
        ("discovery", discovery_first),
    )
    for corpus, metadata in staged_generations:
        with pytest.raises(CatalogGenerationStaleError, match="unavailable"):
            await index.search(
                "staged-document",
                corpus=corpus,
                expected_catalog_digest=metadata.catalog_digest,
            )

    active = await index.activate_generation(
        active_metadata.generation_id,
        expected_generation_digest=active_metadata.generation_digest,
        activated_at=NOW,
    )
    first = await index.activate_generation(
        discovery_first.generation_id,
        expected_generation_digest=discovery_first.generation_digest,
        activated_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
    )
    active_rule_id = active_documents[0].rule_id
    discovery_rule_id = discovery_documents[0].rule_id
    active_results = await index.search(active_rule_id, corpus="active", k=1)
    first_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in active_results} == {active.generation_id}
    assert {item.generation_id for item in first_results} == {first.generation_id}
    assert all(item.corpus == "active" for item in active_results)
    assert all(item.corpus == "discovery" for item in first_results)

    assert await index.stage_generation(discovery_second, changed_discovery_documents) == 8_487
    second = await index.activate_generation(
        discovery_second.generation_id,
        expected_generation_digest=discovery_second.generation_digest,
        activated_at=datetime(2026, 8, 13, 2, tzinfo=UTC),
    )
    assert await index.active_generation("active") == active
    assert await index.search(active_rule_id, corpus="active", k=1) == active_results
    second_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in second_results} == {second.generation_id}

    compatibility = OntologyGenerationCompatibilityReceipt(
        previous_release_digest=first.ontology_release_digest,
        candidate_release_digest=second.ontology_release_digest,
        checked_declarations=(),
        added_declarations=(),
    )
    rollback = await index.rollback_generation(
        first.generation_id,
        expected_active_generation_id=second.generation_id,
        expected_active_generation_digest=second.generation_digest,
        expected_target_generation_digest=first.generation_digest,
        expected_validation_receipt_digest=first.validation_receipt_digest or "",
        ontology_compatibility_receipt=compatibility,
        rolled_back_at=datetime(2026, 8, 13, 3, tzinfo=UTC),
    )

    assert rollback.reactivated_generation_id == first.generation_id
    assert await index.active_generation("active") == active
    assert await index.search(active_rule_id, corpus="active", k=1) == active_results
    rolled_back_results = await index.search(discovery_rule_id, corpus="discovery", k=1)
    assert {item.generation_id for item in rolled_back_results} == {first.generation_id}
