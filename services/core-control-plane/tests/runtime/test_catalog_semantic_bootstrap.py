from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import fdai.runtime.bootstrap_lifecycle as lifecycle
import pytest
from fdai.core.readiness import ReadinessDecision, reduce_startup_readiness
from fdai.rule_catalog.schema.catalog_search import catalog_search_schema_digest
from fdai.runtime.bootstrap_lifecycle import (
    build_catalog_semantic_runtime_binding,
    catalog_semantic_readiness_registration,
)
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    build_document_digest_manifest,
    catalog_generation_digest,
)
from fdai.shared.providers.startup_probe import StartupProbeRequest

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)
DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)
DOCUMENT_DIGEST = "sha256:" + ("c" * 64)
VALIDATION_DIGEST = "sha256:" + ("d" * 64)


class _Embedder:
    dim = 384

    async def embed(self, text: str) -> tuple[float, ...]:
        return (float(bool(text)),) * self.dim


class _Index:
    active: CatalogGenerationMetadata | None = None
    failure: Exception | None = None

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def active_generation(self, corpus: str = "active") -> CatalogGenerationMetadata | None:
        assert corpus == "active"
        if self.failure is not None:
            raise self.failure
        return self.active


def _generation(*, ontology_release_digest: str = DIGEST_B) -> CatalogGenerationMetadata:
    manifest = build_document_digest_manifest((DOCUMENT_DIGEST,))
    generation_digest = catalog_generation_digest(
        corpus="active",
        catalog_digest=DIGEST_A,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="catalog-active-v1",
        embedding_model_version="embedding-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
    )
    return CatalogGenerationMetadata(
        generation_id="catalog-active-1",
        generation_digest=generation_digest,
        corpus="active",
        catalog_digest=DIGEST_A,
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=ontology_release_digest,
        embedding_space_id="catalog-active-v1",
        embedding_model_version="embedding-v1",
        embedding_dimension=384,
        document_digest_manifest=manifest,
        state="active",
        validation_receipt_digest=VALIDATION_DIGEST,
        activated_at=NOW,
    )


@pytest.fixture(autouse=True)
def _patch_index(monkeypatch: pytest.MonkeyPatch) -> None:
    _Index.active = None
    _Index.failure = None
    monkeypatch.setattr(lifecycle, "PostgresCatalogSemanticIndex", _Index)
    monkeypatch.setattr(lifecycle, "rule_reference_catalog_digest", lambda _rules: DIGEST_A)


async def test_catalog_semantic_binding_accepts_only_exact_active_generation() -> None:
    _Index.active = _generation()

    binding = await build_catalog_semantic_runtime_binding(
        config={"FDAI_STATE_STORE_DSN": "postgresql://catalog"},
        embedder=_Embedder(),
        rules=(),
        ontology_release=SimpleNamespace(digest=DIGEST_B),  # type: ignore[arg-type]
    )

    assert binding.available is True
    assert binding.catalog_digest == DIGEST_A
    assert binding.generation == _Index.active


@pytest.mark.parametrize(
    ("generation", "reason"),
    (
        (None, "catalog_semantic_generation_unavailable"),
        (
            _generation(ontology_release_digest=DIGEST_A),
            "catalog_semantic_generation_stale",
        ),
    ),
)
async def test_catalog_semantic_binding_degrades_missing_or_stale_generation(
    generation: CatalogGenerationMetadata | None,
    reason: str,
) -> None:
    _Index.active = generation

    binding = await build_catalog_semantic_runtime_binding(
        config={"FDAI_STATE_STORE_DSN": "postgresql://catalog"},
        embedder=_Embedder(),
        rules=(),
        ontology_release=SimpleNamespace(digest=DIGEST_B),  # type: ignore[arg-type]
    )

    assert binding.available is False
    assert binding.unavailable_reason == reason


async def test_catalog_semantic_binding_hides_provider_failure_details() -> None:
    _Index.failure = RuntimeError("postgresql://secret@host/catalog")

    binding = await build_catalog_semantic_runtime_binding(
        config={"FDAI_STATE_STORE_DSN": "postgresql://catalog"},
        embedder=_Embedder(),
        rules=(),
        ontology_release=SimpleNamespace(digest=DIGEST_B),  # type: ignore[arg-type]
    )

    assert binding.unavailable_reason == "catalog_semantic_generation_inaccessible"


async def test_catalog_semantic_binding_degrades_without_ontology_release() -> None:
    binding = await build_catalog_semantic_runtime_binding(
        config={"FDAI_STATE_STORE_DSN": "postgresql://catalog"},
        embedder=_Embedder(),
        rules=(),
        ontology_release=None,
    )

    assert binding.unavailable_reason == "catalog_semantic_ontology_unavailable"


async def test_catalog_semantic_readiness_is_optional_degradation() -> None:
    binding = await build_catalog_semantic_runtime_binding(
        config={},
        embedder=_Embedder(),
        rules=(),
        ontology_release=SimpleNamespace(digest=DIGEST_B),  # type: ignore[arg-type]
    )
    specs, probes = catalog_semantic_readiness_registration(binding)
    result = await probes[0].run(
        StartupProbeRequest(
            deadline=NOW + timedelta(seconds=5),
            cost_limit_usd=0,
            model_sample_count=2,
            synthetic_scope=False,
        )
    )
    report = reduce_startup_readiness(specs, (result,), generated_at=NOW)

    assert report.decision is ReadinessDecision.DEGRADED
    assert result.failure_class == "catalog_semantic_state_store_unavailable"
