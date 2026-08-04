from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
)
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.delivery.configuration_baseline_docx import render_configuration_baseline_docx
from fdai.delivery.configuration_drift_knowledge import (
    PinnedConfigurationBaselineKnowledgeSource,
    configuration_baseline_document,
    ingest_configuration_baseline,
)
from fdai.shared.providers.knowledge import EmbeddingKnowledgeSource, KnowledgeDocument

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


class _Embedder:
    async def embed(self, text: str) -> tuple[float, ...]:
        return (float(bool(text)), 1.0)


@dataclass
class _BaselineSource:
    baseline: FrozenConfigurationBaseline

    async def load(self) -> FrozenConfigurationBaseline:
        return self.baseline


@dataclass
class _ObservationSource:
    observation: ConfigurationObservation

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        assert scope == self.observation.scope
        return self.observation


def _observation() -> ConfigurationObservation:
    return ConfigurationObservation(
        scope="example-scope",
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(
            ConfigurationResource(
                local_name="service-a",
                resource_type="example/service",
                region="korea central",
                attributes={"sku": "Standard"},
            ),
        ),
    )


def _baseline(document: bytes) -> FrozenConfigurationBaseline:
    observation = _observation()
    return FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope=observation.scope,
        source="reviewed inventory snapshot",
        document_sha256=hashlib.sha256(document).hexdigest(),
        resources=observation.resources,
    )


def test_document_adapter_pins_version_hash_scope_and_filename(tmp_path: Path) -> None:
    observation = _observation()
    document = render_configuration_baseline_docx(
        observation=observation,
        version="s13-v1",
        created_at=_NOW,
        source="reviewed inventory snapshot",
    )
    path = tmp_path / "baseline.docx"
    path.write_bytes(document)
    baseline = _baseline(document)

    knowledge = configuration_baseline_document(baseline, document_path=path)

    assert knowledge.source_ref == "baseline.docx"
    assert str(tmp_path) not in knowledge.source_ref
    assert knowledge.metadata["baseline_version"] == baseline.version
    assert knowledge.metadata["document_sha256"] == baseline.document_sha256
    assert knowledge.metadata["baseline_sha256"] == baseline.sha256


async def test_ingestion_and_service_produce_exact_citation(tmp_path: Path) -> None:
    observation = _observation()
    document = render_configuration_baseline_docx(
        observation=observation,
        version="s13-v1",
        created_at=_NOW,
        source="reviewed inventory snapshot",
    )
    path = tmp_path / "baseline.docx"
    path.write_bytes(document)
    baseline = _baseline(document)
    knowledge = EmbeddingKnowledgeSource(embedder=_Embedder())

    assert await ingest_configuration_baseline(knowledge, baseline, document_path=path) > 0
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(observation),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=knowledge,
    )

    report = await service.run()

    assert report.knowledge_status is KnowledgeGroundingStatus.CITED
    assert report.knowledge_citations
    assert all(
        citation.startswith("knowledge:baseline.docx#") for citation in report.knowledge_citations
    )


async def test_pinned_chunk_identity_includes_full_document_digest() -> None:
    def document(digest: str) -> KnowledgeDocument:
        return KnowledgeDocument(
            doc_id="configuration-baseline:s13-v1",
            text="Frozen configuration baseline evidence.",
            source_ref="baseline.docx",
            metadata={
                "baseline_version": "s13-v1",
                "document_sha256": digest,
            },
        )

    first_digest = "a" * 64
    second_digest = "b" * 64
    first = await PinnedConfigurationBaselineKnowledgeSource(document(first_digest)).search(
        "s13-v1",
    )
    second = await PinnedConfigurationBaselineKnowledgeSource(document(second_digest)).search(
        "s13-v1",
    )

    assert first[0].chunk_id != second[0].chunk_id
    assert first_digest in first[0].chunk_id
    assert second_digest in second[0].chunk_id


async def test_pinned_source_uses_bounded_lexical_fallback() -> None:
    source = PinnedConfigurationBaselineKnowledgeSource(
        KnowledgeDocument(
            doc_id="configuration-baseline:s13-v1",
            text="Frozen infrastructure topology and configuration evidence.",
            source_ref="baseline.docx",
            metadata={
                "baseline_version": "s13-v1",
                "document_sha256": "a" * 64,
            },
        ),
    )

    grounded = await source.search("show frozen topology evidence")
    unrelated = await source.search("lunch menu forecast")

    assert grounded
    assert grounded[0].score > 0
    assert unrelated == ()


def test_document_adapter_rejects_digest_mismatch(tmp_path: Path) -> None:
    observation = _observation()
    document = render_configuration_baseline_docx(
        observation=observation,
        version="s13-v1",
        created_at=_NOW,
        source="reviewed inventory snapshot",
    )
    path = tmp_path / "baseline.docx"
    path.write_bytes(document + b"changed")

    with pytest.raises(ValueError, match="digest"):
        configuration_baseline_document(_baseline(document), document_path=path)
