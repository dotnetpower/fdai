"""Principal-scoped governed document FunctionType tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    GOVERNED_DOCUMENT_MEASURE_CONCEPT,
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
    governed_document_function,
    governed_document_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)


class _Reader:
    def __init__(self, result: GovernedDocumentCollection) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
    ) -> GovernedDocumentCollection:
        self.calls.append(
            {
                "query": query,
                "principal_ref": principal_ref,
                "principal_role": principal_role,
                "principal_groups": principal_groups,
                "purpose": purpose,
                "limit": limit,
            }
        )
        return self.result


def _collection(
    *,
    excerpts: tuple[GovernedDocumentExcerpt, ...] = (),
    complete: bool = True,
    limitation: str | None = None,
) -> GovernedDocumentCollection:
    return GovernedDocumentCollection(
        excerpts=excerpts,
        observed_at=NOW,
        complete=complete,
        limitation=limitation,
        index_generation="document-index:sha256:" + ("1" * 64),
        access_scope_digest="sha256:" + ("2" * 64),
        retrieval_mode="hybrid",
    )


def _excerpt() -> GovernedDocumentExcerpt:
    return GovernedDocumentExcerpt(
        evidence_ref="document:sha256:" + ("3" * 64),
        document_revision="version:00000000-0000-0000-0000-000000000001:sha256:" + ("4" * 64),
        source_name="recovery-runbook.md",
        source_ref="doc:00000000-0000-0000-0000-000000000001:chunk-1",
        locator="section:recovery/paragraph:2",
        chunk_id="chunk-1",
        text="Verify the health probe before restarting the workload.",
        content_digest="sha256:" + ("5" * 64),
        score=0.91,
    )


async def _invoke(
    reader: _Reader,
    *,
    arguments: dict[str, object] | None = None,
    principal_ref: str | None = "operator-a",
) -> dict[str, object]:
    declaration = governed_document_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        governed_document_function(release, reader=reader),
    )
    result = await registry.invoke(
        GOVERNED_DOCUMENT_FUNCTION_NAME,
        arguments
        or {
            "query": "What does the recovery runbook require?",
            "evidence_mode": "explicit",
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
            principal_ref=principal_ref,
            principal_scope_digest="sha256:" + ("6" * 64),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_governed_document_function_declares_bounded_read_contract() -> None:
    declaration = governed_document_function_type()

    assert declaration.name == GOVERNED_DOCUMENT_FUNCTION_NAME
    assert declaration.output_schema["x-fdai-measure-concepts"] == [
        GOVERNED_DOCUMENT_MEASURE_CONCEPT
    ]
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_governed_document_function_projects_exact_citation_fields() -> None:
    reader = _Reader(_collection(excerpts=(_excerpt(),)))

    result = await _invoke(reader)

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["excerpt_count"] == 1
    assert rows[0]["values"]["instruction_authority"] is False
    assert rows[1]["values"] == {
        "access_scope_digest": "sha256:" + ("2" * 64),
        "chunk_id": "chunk-1",
        "content_digest": "sha256:" + ("5" * 64),
        "document_revision": ("version:00000000-0000-0000-0000-000000000001:sha256:" + ("4" * 64)),
        "evidence_ref": "document:sha256:" + ("3" * 64),
        "execution_authority": False,
        "index_generation": "document-index:sha256:" + ("1" * 64),
        "instruction_authority": False,
        "locator": "section:recovery/paragraph:2",
        "record_kind": "excerpt",
        "retrieval_mode": "hybrid",
        "score": 0.91,
        "source_name": "recovery-runbook.md",
        "source_ref": "doc:00000000-0000-0000-0000-000000000001:chunk-1",
        "text": "Verify the health probe before restarting the workload.",
    }
    assert reader.calls == [
        {
            "query": "What does the recovery runbook require?",
            "principal_ref": "operator-a",
            "principal_role": CeilingRole.READER,
            "principal_groups": frozenset(),
            "purpose": "operations-review",
            "limit": 8,
        }
    ]


async def test_governed_document_function_preserves_incomplete_search() -> None:
    result = await _invoke(
        _Reader(
            _collection(
                excerpts=(_excerpt(),),
                complete=False,
                limitation="candidate_limit_reached",
            )
        )
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "candidate_limit_reached"
    assert result["rows"][0]["values"]["count_posture"] == "minimum"


async def test_governed_document_function_requires_principal_context() -> None:
    with pytest.raises(
        PermissionError,
        match="governed document search requires a principal identity",
    ):
        await _invoke(_Reader(_collection()), principal_ref=None)


@pytest.mark.parametrize(
    "arguments",
    (
        {"query": "", "evidence_mode": "explicit"},
        {"query": "runbook", "evidence_mode": "none"},
        {"query": "runbook", "evidence_mode": "explicit", "limit": True},
        {"query": "runbook", "evidence_mode": "explicit", "limit": 9},
    ),
)
async def test_governed_document_function_rejects_invalid_arguments(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        await _invoke(_Reader(_collection()), arguments=arguments)
