"""Complete, principal-scoped conversation document export tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from uuid import UUID, uuid5

import pytest
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.document_export import (
    ConversationDocumentExporter,
)
from fdai_operator_service.postgres_semantic_turn_store import StoredSemanticResult

_TEST_NAMESPACE = UUID(int=0)
_SOURCE_REQUEST_ID = str(uuid5(_TEST_NAMESPACE, "document-source"))
_PROJECTION_ID = str(uuid5(_TEST_NAMESPACE, "document-projection"))


def _result(*, returned_rows: int = 2, total_rows: int = 2) -> StoredSemanticResult:
    rows = (
        [
            {"row_id": "row-1", "values": {"name": "api|one", "status": "ready"}},
            {"row_id": "row-2", "values": {"name": "api-two", "status": "unknown"}},
        ]
        + [
            {
                "row_id": f"row-{index}",
                "values": {"name": f"api-{index}", "status": "ready"},
            }
            for index in range(3, total_rows + 1)
        ]
    )[:returned_rows]
    return StoredSemanticResult(
        sequence=1,
        event="semantic_turn_result",
        request_id=_SOURCE_REQUEST_ID,
        principal_id="operator-1",
        projection_id=_PROJECTION_ID,
        data={
            "recorded_at": "2026-09-04T08:00:00Z",
            "semantic_result": {
                "disposition": "answered",
                "answer": "Verified resource inventory.",
                "evidence_refs": ["evidence:inventory"],
            },
            "payload": {
                "technical_details": {
                    "kind": "semantic_query_outputs",
                    "outputs": [
                        {
                            "node_id": "resources",
                            "rows": rows,
                            "returned_rows": returned_rows,
                            "total_rows": total_rows,
                            "source_complete": False,
                            "source_truncation_reason": "source_incomplete",
                            "display_truncated": returned_rows != total_rows,
                        }
                    ],
                }
            },
        },
        duplicate=False,
    )


class _Store:
    def __init__(self, result: StoredSemanticResult | None) -> None:
        self.result = result
        self.principal_ids: list[str] = []

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]:
        del request_id, after_sequence, limit
        self.principal_ids.append(principal_id)
        if self.result is None or self.result.principal_id != principal_id:
            return ()
        return (self.result,)


class _Pdf:
    name = "pdf"
    content_type = "application/pdf"

    def encode(self, report: Mapping[str, object]) -> bytes:
        assert report["id"] == "conversation-document"
        return b"%PDF-complete"


async def test_complete_document_exports_all_rows_as_markdown_and_metadata() -> None:
    store = _Store(_result())
    exporter = ConversationDocumentExporter(store=store, pdf_encoder=_Pdf())

    document = await exporter.materialize(
        principal_id="operator-1",
        source_request_id=_SOURCE_REQUEST_ID,
    )
    response = await exporter.read(
        ConversationQuery(
            operation="chat.document.download",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            path_params={
                "request_id": _SOURCE_REQUEST_ID,
                "format": "markdown",
            },
        )
    )

    assert document.expected_rows == document.included_rows == 2
    assert document.metadata(pdf_available=True)["complete"] is True
    assert "pdf_url" not in document.metadata(pdf_available=False)
    assert "| api\\|one | ready |" in document.markdown
    assert "source_incomplete" in document.markdown
    assert response.media_type == "text/markdown; charset=utf-8"
    assert response.body == document.markdown.encode()
    assert store.principal_ids == ["operator-1", "operator-1"]


async def test_document_pdf_reuses_the_bounded_report_encoder() -> None:
    exporter = ConversationDocumentExporter(store=_Store(_result()), pdf_encoder=_Pdf())

    response = await exporter.read(
        ConversationQuery(
            operation="chat.document.download",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            path_params={
                "request_id": _SOURCE_REQUEST_ID,
                "format": "pdf",
            },
        )
    )

    assert response.body == b"%PDF-complete"
    assert response.media_type == "application/pdf"
    assert ("X-FDAI-Included-Rows", "2") in response.headers
    assert (
        "X-FDAI-Artifact-SHA256",
        hashlib.sha256(b"%PDF-complete").hexdigest(),
    ) in response.headers
    assert ("Cache-Control", "private, no-store") in response.headers


async def test_complete_document_preserves_all_24_projected_rows() -> None:
    exporter = ConversationDocumentExporter(
        store=_Store(_result(returned_rows=24, total_rows=24)),
        pdf_encoder=_Pdf(),
    )

    document = await exporter.materialize(
        principal_id="operator-1",
        source_request_id=_SOURCE_REQUEST_ID,
    )

    assert document.included_rows == document.expected_rows == 24
    assert "| api\\|one | ready |" in document.markdown
    assert "| api-24 | ready |" in document.markdown


async def test_document_export_rejects_partial_rows_and_foreign_sources() -> None:
    partial = ConversationDocumentExporter(
        store=_Store(_result(returned_rows=1, total_rows=2)),
    )
    with pytest.raises(ConversationBoundaryError) as incomplete:
        await partial.materialize(
            principal_id="operator-1",
            source_request_id=_SOURCE_REQUEST_ID,
        )
    assert incomplete.value.code == "document_source_incomplete"

    foreign = ConversationDocumentExporter(store=_Store(_result()))
    with pytest.raises(ConversationBoundaryError) as absent:
        await foreign.materialize(
            principal_id="operator-2",
            source_request_id=_SOURCE_REQUEST_ID,
        )
    assert absent.value.code == "document_source_not_found"


async def test_document_export_rejects_mixed_non_tabular_content() -> None:
    result = _result()
    payload = result.data["payload"]
    assert isinstance(payload, dict)
    details = payload["technical_details"]
    assert isinstance(details, dict)
    outputs = details["outputs"]
    assert isinstance(outputs, list)
    outputs.append({"node_id": "summary", "value": "omitted if accepted"})
    exporter = ConversationDocumentExporter(store=_Store(result))

    with pytest.raises(ConversationBoundaryError) as raised:
        await exporter.materialize(
            principal_id="operator-1",
            source_request_id=_SOURCE_REQUEST_ID,
        )

    assert raised.value.code == "document_source_unsupported"


async def test_document_download_rejects_noncanonical_request_id() -> None:
    exporter = ConversationDocumentExporter(store=_Store(_result()))

    with pytest.raises(ConversationBoundaryError) as raised:
        await exporter.read(
            ConversationQuery(
                operation="chat.document.download",
                scope=PrincipalScope("operator-1", frozenset({"Reader"})),
                path_params={
                    "request_id": f"{{{_SOURCE_REQUEST_ID}}}",
                    "format": "markdown",
                },
            )
        )

    assert raised.value.code == "document_request_invalid"
