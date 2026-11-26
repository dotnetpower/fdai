from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai_service_contracts.system_knowledge import (
    SystemKnowledgeAuthorityRole,
    SystemKnowledgeCatalog,
    SystemKnowledgeMatch,
    SystemKnowledgeQueryResponse,
    SystemKnowledgeRecord,
    SystemKnowledgeSource,
    SystemKnowledgeSourceKind,
    SystemKnowledgeStatus,
    system_knowledge_digest,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _source() -> SystemKnowledgeSource:
    return SystemKnowledgeSource(
        source_kind=SystemKnowledgeSourceKind.DOC,
        authority_role=SystemKnowledgeAuthorityRole.DESIGN,
        path="docs/roadmap/interfaces/system-knowledge-service.md",
        symbol="Revised design",
        line_start=60,
        line_end=70,
        blob_sha="a" * 40,
    )


def _record() -> SystemKnowledgeRecord:
    body = {
        "knowledge_id": "system-knowledge-service",
        "subject_id": "system-knowledge-service",
        "title": "System Knowledge Service",
        "status": SystemKnowledgeStatus.IN_PROGRESS,
        "owner": "Muninn",
        "question_aliases": ("How does FDAI answer design questions?",),
        "designed_behavior": ("The service answers from a release-bound catalog.",),
        "implemented_behavior": (),
        "limitations": ("Production validation is pending.",),
        "sources": (_source(),),
        "execution_authority": False,
    }
    return SystemKnowledgeRecord(**body, record_digest=system_knowledge_digest(body))


def _catalog() -> SystemKnowledgeCatalog:
    body = {
        "schema_version": "1.0.0",
        "source_revision": "b" * 40,
        "generated_at": NOW,
        "records": (_record(),),
        "execution_authority": False,
    }
    return SystemKnowledgeCatalog(**body, catalog_digest=system_knowledge_digest(body))


def test_catalog_and_response_digests_bind_complete_content() -> None:
    catalog = _catalog()
    match = SystemKnowledgeMatch(
        record=catalog.records[0],
        score=2.0,
        match_kind="exact_alias",
    )
    body = {
        "schema_version": "1.0.0",
        "outcome": "answered",
        "matches": (match,),
        "observed_at": NOW,
        "source_revision": catalog.source_revision,
        "catalog_digest": catalog.catalog_digest,
        "complete": True,
        "limitation": None,
        "execution_authority": False,
    }

    response = SystemKnowledgeQueryResponse(
        **body,
        response_digest=system_knowledge_digest(body),
    )

    assert response.matches[0].record.sources[0].evidence_ref.startswith("repo:")
    assert response.execution_authority is False


def test_catalog_rejects_duplicate_aliases_across_records() -> None:
    first = _record()
    body = first.model_dump(mode="python", exclude={"record_digest"})
    body["knowledge_id"] = "other-service"
    body["subject_id"] = "other-service"
    second = SystemKnowledgeRecord(**body, record_digest=system_knowledge_digest(body))
    catalog_body = {
        "schema_version": "1.0.0",
        "source_revision": "b" * 40,
        "generated_at": NOW,
        "records": tuple(sorted((first, second), key=lambda record: record.knowledge_id)),
        "execution_authority": False,
    }

    with pytest.raises(ValueError, match="aliases"):
        SystemKnowledgeCatalog(
            **catalog_body,
            catalog_digest=system_knowledge_digest(catalog_body),
        )


def test_source_rejects_repository_escape() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        SystemKnowledgeSource(
            source_kind=SystemKnowledgeSourceKind.DOC,
            authority_role=SystemKnowledgeAuthorityRole.DESIGN,
            path="../secret",
            symbol="Hidden",
            line_start=1,
            line_end=1,
            blob_sha="a" * 40,
        )
