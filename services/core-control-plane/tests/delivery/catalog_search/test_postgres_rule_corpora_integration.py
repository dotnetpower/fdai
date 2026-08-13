from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
import yaml
from fdai.delivery.catalog_search.postgres import (
    PostgresCatalogSemanticIndex,
    PostgresCatalogSemanticIndexConfig,
)
from fdai.rule_catalog.schema.catalog_search import (
    build_catalog_search_documents,
    build_discovery_catalog_search_documents,
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.discovery_rule import load_discovery_rule_catalog
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.rule_semantic_generation import build_document_digest_manifest
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogCorpus,
    CatalogGenerationMetadata,
    CatalogSearchDocument,
    catalog_generation_digest,
    catalog_search_document_digest,
)

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[5]
RULE_CATALOG_ROOT = REPO_ROOT / "rule-catalog"
ACTIVE_ID = "integration-rule-search-active-complete"
DISCOVERY_FIRST_ID = "integration-rule-search-discovery-complete-first"
DISCOVERY_SECOND_ID = "integration-rule-search-discovery-complete-second"
GENERATION_IDS = (ACTIVE_ID, DISCOVERY_FIRST_ID, DISCOVERY_SECOND_ID)


class _Embedder:
    async def embed(self, text: str) -> tuple[float, ...]:
        seed = float(sum(text.encode("utf-8")) % 31) / 31.0
        return (seed,) * 384


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    _dsn()
    result = subprocess.run(  # noqa: S603 - controlled migration command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _metadata(
    *,
    generation_id: str,
    corpus: CatalogCorpus,
    catalog_digest: str,
    ontology_release_digest: str,
    documents: tuple[CatalogSearchDocument, ...],
) -> CatalogGenerationMetadata:
    manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    generation_digest = catalog_generation_digest(
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="integration-v1",
        embedding_model_version="integration-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
    )
    return CatalogGenerationMetadata(
        generation_id=generation_id,
        generation_digest=generation_digest,
        corpus=corpus,
        catalog_digest=catalog_digest,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="integration-v1",
        embedding_model_version="integration-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
        validation_receipt_digest=_digest(f"validated\0{generation_digest}"),
    )


def _load_corpora() -> tuple[
    tuple[CatalogSearchDocument, ...],
    CatalogGenerationMetadata,
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
    active_rules = load_rule_catalog(
        RULE_CATALOG_ROOT / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=RULE_CATALOG_ROOT / "remediation",
    )
    policy_semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in active_rules
    }
    active_documents = build_catalog_search_documents(
        rules=active_rules,
        action_types=ontology.action_types,
        policy_semantics=policy_semantics,
    )
    ontology_release_digest = ontology.build_release().digest
    active_metadata = _metadata(
        generation_id=ACTIVE_ID,
        corpus="active",
        catalog_digest=rule_reference_catalog_digest(active_rules),
        ontology_release_digest=ontology_release_digest,
        documents=active_documents,
    )
    discovery_rules = load_discovery_rule_catalog(
        RULE_CATALOG_ROOT / "collected",
        schema_registry=registry,
    )
    discovery_documents = build_discovery_catalog_search_documents(discovery_rules)
    discovery_metadata = _metadata(
        generation_id=DISCOVERY_FIRST_ID,
        corpus="discovery",
        catalog_digest=rule_reference_catalog_digest(discovery_rules),
        ontology_release_digest=ontology_release_digest,
        documents=discovery_documents,
    )
    return active_documents, active_metadata, discovery_documents, discovery_metadata


async def _cleanup() -> None:
    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        await connection.execute(
            "DELETE FROM catalog_search_generation WHERE generation_id=ANY(%s::text[])",
            (list(GENERATION_IDS),),
        )


async def test_postgres_complete_rule_corpora_have_isolated_lifecycles() -> None:
    _upgrade()
    await _cleanup()
    active_documents, active_metadata, discovery_documents, discovery_first_metadata = (
        _load_corpora()
    )
    changed_discovery_documents = (
        replace(discovery_documents[0], text=f"{discovery_documents[0].text}\ncandidate-refresh"),
        *discovery_documents[1:],
    )
    discovery_second_metadata = _metadata(
        generation_id=DISCOVERY_SECOND_ID,
        corpus="discovery",
        catalog_digest=discovery_first_metadata.catalog_digest,
        ontology_release_digest=active_metadata.ontology_release_digest,
        documents=changed_discovery_documents,
    )
    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(dsn=_dsn()),
        embedder=_Embedder(),
    )

    try:
        assert len(active_documents) == 62
        assert len(discovery_documents) == 8_487
        assert active_metadata.document_digest_manifest.document_count == 62
        assert discovery_first_metadata.document_digest_manifest.document_count == 8_487
        assert len(discovery_first_metadata.document_digest_manifest.chunks) == 34

        assert await index.stage_generation(active_metadata, active_documents) == 62
        assert await index.stage_generation(discovery_first_metadata, discovery_documents) == 8_487
        active = await index.activate_generation(
            ACTIVE_ID,
            expected_generation_digest=active_metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=datetime(2026, 8, 13, tzinfo=UTC),
        )
        discovery_first = await index.activate_generation(
            DISCOVERY_FIRST_ID,
            expected_generation_digest=discovery_first_metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
        )
        active_rule_id = active_documents[0].rule_id
        active_results = await index.search(active_rule_id, corpus="active", k=1)

        assert (
            await index.stage_generation(discovery_second_metadata, changed_discovery_documents)
            == 8_487
        )
        discovery_second = await index.activate_generation(
            DISCOVERY_SECOND_ID,
            expected_generation_digest=discovery_second_metadata.generation_digest,
            expected_active_generation_id=discovery_first.generation_id,
            expected_active_generation_digest=discovery_first.generation_digest,
            activated_at=datetime(2026, 8, 13, 2, tzinfo=UTC),
        )
        assert await index.active_generation("active") == active
        assert await index.search(active_rule_id, corpus="active", k=1) == active_results

        compatibility = OntologyGenerationCompatibilityReceipt(
            previous_release_digest=discovery_first.ontology_release_digest,
            candidate_release_digest=discovery_second.ontology_release_digest,
            checked_declarations=(),
            added_declarations=(),
        )
        rollback = await index.rollback_generation(
            DISCOVERY_FIRST_ID,
            expected_active_generation_id=DISCOVERY_SECOND_ID,
            expected_active_generation_digest=discovery_second.generation_digest,
            expected_target_generation_digest=discovery_first.generation_digest,
            expected_validation_receipt_digest=(discovery_first.validation_receipt_digest or ""),
            ontology_compatibility_receipt=compatibility,
            rolled_back_at=datetime(2026, 8, 13, 3, tzinfo=UTC),
        )

        assert rollback.reactivated_generation_id == DISCOVERY_FIRST_ID
        assert await index.active_generation("active") == active
        assert await index.search(active_rule_id, corpus="active", k=1) == active_results
        discovery_after = await index.active_generation("discovery")
        assert discovery_after is not None
        assert discovery_after.generation_id == DISCOVERY_FIRST_ID
        assert discovery_after.document_digest_manifest == (
            discovery_first_metadata.document_digest_manifest
        )
    finally:
        await _cleanup()
