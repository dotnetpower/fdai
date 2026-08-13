from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from fdai.delivery.catalog_search.postgres import (
    PostgresCatalogSemanticIndex,
    PostgresCatalogSemanticIndexConfig,
)
from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogGenerationStaleError,
    CatalogSearchDocument,
    build_document_digest_manifest,
    catalog_generation_digest,
    catalog_search_document_digest,
)

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[5]
FIRST_ID = "integration-rule-search-active-first"
SECOND_ID = "integration-rule-search-active-second"
THIRD_ID = "integration-rule-search-active-third"
NOW = datetime(2026, 8, 13, tzinfo=UTC)


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


def _metadata(
    generation_id: str,
    documents: tuple[CatalogSearchDocument, ...],
) -> CatalogGenerationMetadata:
    manifest = build_document_digest_manifest(
        tuple(catalog_search_document_digest(item) for item in documents)
    )
    catalog_digest = "sha256:" + ("a" * 64)
    schema_digest = "sha256:" + ("b" * 64)
    release_digest = "sha256:" + ("c" * 64)
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=catalog_digest,
        semantic_schema_digest=schema_digest,
        ontology_release_digest=release_digest,
        embedding_space_id="integration-v1",
        embedding_model_version="integration-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
    )
    return CatalogGenerationMetadata(
        generation_id=generation_id,
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=catalog_digest,
        semantic_schema_digest=schema_digest,
        ontology_release_digest=release_digest,
        embedding_space_id="integration-v1",
        embedding_model_version="integration-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
        validation_receipt_digest="sha256:" + ("d" * 64),
    )


async def _cleanup() -> None:
    async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
        await connection.execute(
            "DELETE FROM catalog_search_generation WHERE generation_id=ANY(%s::text[])",
            ([FIRST_ID, SECOND_ID, THIRD_ID],),
        )


async def test_postgres_catalog_generation_lifecycle_is_manifest_bound() -> None:
    _upgrade()
    await _cleanup()
    documents = (
        CatalogSearchDocument("rule-a", "deny public access", ("object-storage",)),
        CatalogSearchDocument("rule-b", "require owner tag", ("resource-tag",)),
    )
    changed_documents = (
        documents[0],
        replace(documents[1], text="require reviewed owner tag"),
    )
    delayed_documents = (
        documents[0],
        replace(documents[1], text="require delayed owner tag"),
    )
    first_metadata = _metadata(FIRST_ID, documents)
    second_metadata = _metadata(SECOND_ID, changed_documents)
    third_metadata = _metadata(THIRD_ID, delayed_documents)
    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(dsn=_dsn()),
        embedder=_Embedder(),
    )
    try:
        assert await index.stage_generation(first_metadata, documents) == 2
        assert await index.active_generation() is None
        assert await index.stage_generation(first_metadata, documents) == 0
        snapshot = await index.generation_validation_snapshot(FIRST_ID)
        assert snapshot is not None
        assert snapshot.metadata == first_metadata
        assert tuple(document.rule_id for document in snapshot.documents) == (
            "rule-a",
            "rule-b",
        )
        assert all(document.generation_id == FIRST_ID for document in snapshot.documents)

        first = await index.activate_generation(
            FIRST_ID,
            expected_generation_digest=first_metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=NOW,
        )
        repeated_activation = await index.activate_generation(
            FIRST_ID,
            expected_generation_digest=first_metadata.generation_digest,
            expected_active_generation_id=None,
            expected_active_generation_digest=None,
            activated_at=NOW,
        )
        assert repeated_activation == first
        assert first.document_digest_manifest == first_metadata.document_digest_manifest
        first_results = await index.search("public access", k=2)
        assert first_results
        assert {item.generation_id for item in first_results} == {FIRST_ID}
        bounded_results = await index.search(
            "rule",
            k=2,
            candidate_rule_ids=frozenset({"rule-b"}),
        )
        assert [item.rule_id for item in bounded_results] == ["rule-b"]

        assert await index.stage_generation(second_metadata, changed_documents) == 2
        assert await index.stage_generation(third_metadata, delayed_documents) == 2
        second = await index.activate_generation(
            SECOND_ID,
            expected_generation_digest=second_metadata.generation_digest,
            expected_active_generation_id=first.generation_id,
            expected_active_generation_digest=first.generation_digest,
            activated_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="precedes active generation"):
            await index.activate_generation(
                THIRD_ID,
                expected_generation_digest=third_metadata.generation_digest,
                expected_active_generation_id=second.generation_id,
                expected_active_generation_digest=second.generation_digest,
                activated_at=datetime(2026, 8, 13, 0, 30, tzinfo=UTC),
            )
        with pytest.raises(CatalogGenerationStaleError, match="stale"):
            await index.activate_generation(
                THIRD_ID,
                expected_generation_digest=third_metadata.generation_digest,
                expected_active_generation_id=first.generation_id,
                expected_active_generation_digest=first.generation_digest,
                activated_at=datetime(2026, 8, 13, 1, 30, tzinfo=UTC),
            )
        with pytest.raises(CatalogGenerationStaleError, match="stale"):
            await index.activate_generation(
                FIRST_ID,
                expected_generation_digest=first_metadata.generation_digest,
                expected_active_generation_id=None,
                expected_active_generation_digest=None,
                activated_at=NOW,
            )
        active_after_stale = await index.active_generation()
        assert active_after_stale == second
        async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
            state_cursor = await connection.execute(
                "SELECT generation_id, state FROM catalog_search_generation "
                "WHERE generation_id=ANY(%s::text[])",
                ([FIRST_ID, SECOND_ID, THIRD_ID],),
            )
            states = {str(row[0]): str(row[1]) for row in await state_cursor.fetchall()}
        assert states == {FIRST_ID: "retired", SECOND_ID: "active", THIRD_ID: "staged"}
        with pytest.raises(CatalogGenerationStaleError, match="stale"):
            await index.search("owner tag", expected_catalog_digest="sha256:" + ("e" * 64))

        compatibility = OntologyGenerationCompatibilityReceipt(
            previous_release_digest=first.ontology_release_digest,
            candidate_release_digest=second.ontology_release_digest,
            checked_declarations=(),
            added_declarations=(),
        )
        rolled_back_at = datetime(2026, 8, 13, 2, tzinfo=UTC)
        with pytest.raises(ValueError, match="rollback time"):
            await index.rollback_generation(
                FIRST_ID,
                expected_active_generation_id=SECOND_ID,
                expected_active_generation_digest=second.generation_digest,
                expected_target_generation_digest=first.generation_digest,
                expected_validation_receipt_digest=first.validation_receipt_digest or "",
                ontology_compatibility_receipt=compatibility,
                rolled_back_at=datetime(2026, 8, 12, tzinfo=UTC),
            )
        rollback = await index.rollback_generation(
            FIRST_ID,
            expected_active_generation_id=SECOND_ID,
            expected_active_generation_digest=second.generation_digest,
            expected_target_generation_digest=first.generation_digest,
            expected_validation_receipt_digest=first.validation_receipt_digest or "",
            ontology_compatibility_receipt=compatibility,
            rolled_back_at=rolled_back_at,
        )
        repeated = await index.rollback_generation(
            FIRST_ID,
            expected_active_generation_id=SECOND_ID,
            expected_active_generation_digest=second.generation_digest,
            expected_target_generation_digest=first.generation_digest,
            expected_validation_receipt_digest=first.validation_receipt_digest or "",
            ontology_compatibility_receipt=compatibility,
            rolled_back_at=rolled_back_at,
        )
        with pytest.raises(ValueError, match="target catalog validation receipt mismatch"):
            await index.rollback_generation(
                FIRST_ID,
                expected_active_generation_id=SECOND_ID,
                expected_active_generation_digest=second.generation_digest,
                expected_target_generation_digest=first.generation_digest,
                expected_validation_receipt_digest="sha256:" + ("e" * 64),
                ontology_compatibility_receipt=compatibility,
                rolled_back_at=rolled_back_at,
            )
        with pytest.raises(ValueError, match="active catalog generation digest mismatch"):
            await index.rollback_generation(
                FIRST_ID,
                expected_active_generation_id=SECOND_ID,
                expected_active_generation_digest="sha256:" + ("e" * 64),
                expected_target_generation_digest=first.generation_digest,
                expected_validation_receipt_digest=first.validation_receipt_digest or "",
                ontology_compatibility_receipt=compatibility,
                rolled_back_at=rolled_back_at,
            )

        assert rollback.receipt_digest == repeated.receipt_digest
        active = await index.active_generation()
        assert active is not None
        assert active.generation_id == FIRST_ID
        assert active.document_digest_manifest == first_metadata.document_digest_manifest

        async with await psycopg.AsyncConnection.connect(_dsn()) as connection:
            await connection.execute(
                "UPDATE catalog_search_generation SET document_digest_chunks=%s::jsonb "
                "WHERE generation_id=%s",
                ('[{"document_count": 2}]', FIRST_ID),
            )
        with pytest.raises(ValueError, match="chunk index"):
            await index.active_generation()
    finally:
        await _cleanup()
