"""Generate complete authenticated documents from durable semantic results."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    JsonObject,
)
from fdai_operator_service.families.operations import ReportPdfEncoder, ReportPdfEncodingError
from fdai_operator_service.postgres_semantic_turn_store import StoredSemanticResult

_LOGGER = logging.getLogger(__name__)
_MAX_DOCUMENT_ROWS = 40
_MAX_DOCUMENT_COLUMNS = 16
_MAX_MARKDOWN_BYTES = 192 * 1024


class SemanticDocumentStore(Protocol):
    """Read one principal-owned terminal semantic result."""

    async def replay_semantic_turn(
        self,
        *,
        principal_id: str,
        request_id: str,
        after_sequence: int | None,
        limit: int = 100,
    ) -> tuple[StoredSemanticResult, ...]: ...


@dataclass(frozen=True, slots=True)
class MaterializedConversationDocument:
    """One complete immutable document and its downloadable report envelope."""

    source_request_id: str
    markdown: str
    report: Mapping[str, object]
    expected_rows: int
    included_rows: int
    sha256: str

    def metadata(self, *, pdf_available: bool) -> JsonObject:
        return cast(
            JsonObject,
            {
                "source_request_id": self.source_request_id,
                "expected_rows": self.expected_rows,
                "included_rows": self.included_rows,
                "complete": True,
                "sha256": self.sha256,
                "preview_markdown": self.markdown,
                "markdown_url": f"/chat/documents/{self.source_request_id}/markdown",
                **(
                    {"pdf_url": f"/chat/documents/{self.source_request_id}/pdf"}
                    if pdf_available
                    else {}
                ),
            },
        )


@dataclass(frozen=True, slots=True)
class ConversationDocumentExporter:
    """Materialize and download complete documents from owned semantic evidence."""

    store: SemanticDocumentStore
    pdf_encoder: ReportPdfEncoder | None = None

    async def materialize(
        self,
        *,
        principal_id: str,
        source_request_id: str,
    ) -> MaterializedConversationDocument:
        results = await self.store.replay_semantic_turn(
            principal_id=principal_id,
            request_id=source_request_id,
            after_sequence=None,
            limit=1,
        )
        if not results:
            raise ConversationBoundaryError(
                404,
                "document_source_not_found",
                "verified document source was not found",
            )
        return _materialize(results[0])

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Return one authenticated Markdown or PDF download."""

        source_request_id = _canonical_request_id(_path_text(query.path_params, "request_id"))
        format_name = _path_text(query.path_params, "format")
        if format_name not in {"markdown", "pdf"}:
            raise ConversationBoundaryError(
                400,
                "document_format_invalid",
                "document format must be markdown or pdf",
            )
        document = await self.materialize(
            principal_id=query.scope.subject_id,
            source_request_id=source_request_id,
        )
        if format_name == "markdown":
            payload = document.markdown.encode("utf-8")
            media_type = "text/markdown; charset=utf-8"
            filename = "fdai-conversation-document.md"
        else:
            if self.pdf_encoder is None:
                raise ConversationBoundaryError(
                    503,
                    "document_pdf_unavailable",
                    "document PDF encoding is unavailable",
                )
            try:
                payload = self.pdf_encoder.encode(document.report)
            except ReportPdfEncodingError as exc:
                raise ConversationBoundaryError(
                    503,
                    "document_pdf_unavailable",
                    "document PDF encoding is unavailable",
                ) from exc
            media_type = self.pdf_encoder.content_type
            filename = "fdai-conversation-document.pdf"
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        _LOGGER.info(
            "conversation_document_downloaded",
            extra={
                "source_request_id": source_request_id,
                "format": format_name,
                "included_rows": document.included_rows,
                "sha256": payload_sha256,
            },
        )
        return ConversationResponse(
            body=payload,
            media_type=media_type,
            headers=(
                ("Content-Disposition", f'attachment; filename="{filename}"'),
                ("Cache-Control", "private, no-store"),
                ("Vary", "Authorization"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-FDAI-Artifact-SHA256", payload_sha256),
                ("X-FDAI-Included-Rows", str(document.included_rows)),
                ("X-FDAI-Expected-Rows", str(document.expected_rows)),
            ),
        )


def _materialize(result: StoredSemanticResult) -> MaterializedConversationDocument:
    projection = result.data
    semantic = _mapping(projection.get("semantic_result"), "semantic_result")
    if semantic.get("disposition") != "answered":
        raise ConversationBoundaryError(
            409,
            "document_source_not_answered",
            "document source is not a verified answer",
        )
    evidence_refs = semantic.get("evidence_refs")
    if (
        not isinstance(evidence_refs, Sequence)
        or isinstance(evidence_refs, (str, bytes))
        or not evidence_refs
        or any(not isinstance(item, str) or not item for item in evidence_refs)
    ):
        raise ConversationBoundaryError(
            409,
            "document_source_unverified",
            "document source has no verified evidence references",
        )
    payload = _mapping(projection.get("payload"), "payload")
    details = _mapping(payload.get("technical_details"), "technical_details")
    outputs = details.get("outputs")
    if not isinstance(outputs, Sequence) or isinstance(outputs, (str, bytes)):
        raise ConversationBoundaryError(
            409,
            "document_source_unsupported",
            "document source has no tabular output",
        )
    tables: list[tuple[str, tuple[str, ...], list[Mapping[str, object]]]] = []
    expected_rows = 0
    included_rows = 0
    source_complete = True
    source_limitations: list[str] = []
    for output_index, raw_output in enumerate(outputs, start=1):
        if not isinstance(raw_output, Mapping) or "rows" not in raw_output:
            raise ConversationBoundaryError(
                409,
                "document_source_unsupported",
                "document source contains an unsupported non-tabular output",
            )
        rows = raw_output.get("rows")
        returned_rows = raw_output.get("returned_rows")
        total_rows = raw_output.get("total_rows")
        if (
            not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes))
            or not isinstance(returned_rows, int)
            or isinstance(returned_rows, bool)
            or not isinstance(total_rows, int)
            or isinstance(total_rows, bool)
            or returned_rows != len(rows)
            or returned_rows != total_rows
            or raw_output.get("display_truncated") is not False
        ):
            raise ConversationBoundaryError(
                409,
                "document_source_incomplete",
                "complete document rows are unavailable; rerun the source query",
            )
        expected_rows += total_rows
        included_rows += returned_rows
        if included_rows > _MAX_DOCUMENT_ROWS:
            raise ConversationBoundaryError(
                409,
                "document_row_limit_exceeded",
                "complete document exceeds the supported row limit",
            )
        normalized_rows = [_row(row) for row in rows]
        columns = _columns(normalized_rows)
        tables.append((f"Verified records {output_index}", columns, normalized_rows))
        if raw_output.get("source_complete") is not True:
            source_complete = False
        reason = raw_output.get("source_truncation_reason")
        if isinstance(reason, str) and reason:
            source_limitations.append(reason)
    if not tables:
        raise ConversationBoundaryError(
            409,
            "document_source_unsupported",
            "document source has no tabular output",
        )
    recorded_at = projection.get("recorded_at")
    if not isinstance(recorded_at, str) or not recorded_at:
        raise ConversationBoundaryError(
            409,
            "document_source_malformed",
            "document source timestamp is unavailable",
        )
    answer = semantic.get("answer")
    if not isinstance(answer, str) or not answer:
        raise ConversationBoundaryError(
            409,
            "document_source_malformed",
            "document source summary is unavailable",
        )
    report = _report(
        source_request_id=result.request_id,
        recorded_at=recorded_at,
        answer=answer,
        evidence_refs=tuple(cast(Sequence[str], evidence_refs)),
        tables=tables,
        expected_rows=expected_rows,
        included_rows=included_rows,
        source_complete=source_complete,
        source_limitations=tuple(dict.fromkeys(source_limitations)),
    )
    markdown = _markdown(report)
    encoded = markdown.encode("utf-8")
    if len(encoded) > _MAX_MARKDOWN_BYTES:
        raise ConversationBoundaryError(
            409,
            "document_size_limit_exceeded",
            "complete document exceeds the supported size limit",
        )
    return MaterializedConversationDocument(
        source_request_id=result.request_id,
        markdown=markdown,
        report=report,
        expected_rows=expected_rows,
        included_rows=included_rows,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _report(
    *,
    source_request_id: str,
    recorded_at: str,
    answer: str,
    evidence_refs: tuple[str, ...],
    tables: list[tuple[str, tuple[str, ...], list[Mapping[str, object]]]],
    expected_rows: int,
    included_rows: int,
    source_complete: bool,
    source_limitations: tuple[str, ...],
) -> Mapping[str, object]:
    return {
        "id": "conversation-document",
        "version": "1.0.0",
        "name": "FDAI verified conversation document",
        "description": answer,
        "generated_at": recorded_at,
        "provenance": {
            "source_request_id": source_request_id,
            "evidence_refs": list(evidence_refs),
            "expected_rows": expected_rows,
            "included_rows": included_rows,
            "complete": included_rows == expected_rows,
            "source_complete": source_complete,
            "source_limitations": list(source_limitations),
            "execution_authority": False,
        },
        "widgets": [
            {
                "id": f"records-{index}",
                "type": "table",
                "title": title,
                "data": {
                    "columns": list(columns),
                    "rows": [{column: row.get(column) for column in columns} for row in rows],
                },
                "error": None,
            }
            for index, (title, columns, rows) in enumerate(tables, start=1)
        ],
    }


def _markdown(report: Mapping[str, object]) -> str:
    provenance = _mapping(report.get("provenance"), "provenance")
    lines = [
        f"# {_markdown_text(report['name'])}",
        "",
        str(report["description"]).strip(),
        "",
        "## Document scope",
        "",
        f"- Generated at: `{_markdown_text(report['generated_at'])}`",
        f"- Expected rows: {provenance['expected_rows']}",
        f"- Included rows: {provenance['included_rows']}",
        f"- Complete: `{str(provenance['complete']).lower()}`",
        f"- Source complete: `{str(provenance['source_complete']).lower()}`",
        "- Execution authority: `false`",
        "",
    ]
    limitations = provenance.get("source_limitations")
    if (
        isinstance(limitations, Sequence)
        and not isinstance(limitations, (str, bytes))
        and limitations
    ):
        lines.extend(
            [
                "## Evidence limitations",
                "",
                *(f"- `{_markdown_text(item)}`" for item in limitations),
                "",
            ]
        )
    widgets = report.get("widgets")
    if not isinstance(widgets, Sequence) or isinstance(widgets, (str, bytes)):
        raise ConversationBoundaryError(
            409, "document_source_malformed", "document widgets are invalid"
        )
    for widget in widgets:
        data = _mapping(_mapping(widget, "widget").get("data"), "widget.data")
        columns = data.get("columns")
        rows = data.get("rows")
        if (
            not isinstance(columns, Sequence)
            or isinstance(columns, (str, bytes))
            or not isinstance(rows, Sequence)
            or isinstance(rows, (str, bytes))
        ):
            raise ConversationBoundaryError(
                409,
                "document_source_malformed",
                "document table is invalid",
            )
        safe_columns = [str(column) for column in columns]
        lines.extend(
            [
                f"## {_markdown_text(_mapping(widget, 'widget').get('title', 'Verified records'))}",
                "",
                "| " + " | ".join(_markdown_cell(column) for column in safe_columns) + " |",
                "| " + " | ".join("---" for _column in safe_columns) + " |",
            ]
        )
        for row in rows:
            row_mapping = _mapping(row, "document row")
            lines.append(
                "| "
                + " | ".join(_markdown_cell(row_mapping.get(column)) for column in safe_columns)
                + " |"
            )
        lines.append("")
    lines.extend(
        [
            "## Evidence references",
            "",
            *(
                f"- `{_markdown_text(reference)}`"
                for reference in cast(Sequence[str], provenance["evidence_refs"])
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _row(value: object) -> Mapping[str, object]:
    row = _mapping(value, "document row")
    values = _mapping(row.get("values"), "document row values")
    return {str(key): item for key, item in values.items()}


def _columns(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    columns = tuple(dict.fromkeys(str(key) for row in rows for key in row))
    if not columns or len(columns) > _MAX_DOCUMENT_COLUMNS:
        raise ConversationBoundaryError(
            409,
            "document_column_limit_exceeded",
            "document columns exceed the supported bound",
        )
    return columns


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConversationBoundaryError(409, "document_source_malformed", f"{label} is malformed")
    return value


def _path_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > 128:
        raise ConversationBoundaryError(400, "document_path_invalid", "document path is malformed")
    return item


def _canonical_request_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ConversationBoundaryError(
            400,
            "document_request_invalid",
            "document request id must be a UUID",
        ) from exc
    if str(parsed) != value.lower():
        raise ConversationBoundaryError(
            400,
            "document_request_invalid",
            "document request id must be a canonical hyphenated UUID",
        )
    return str(parsed)


def _markdown_text(value: object) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _markdown_cell(value: object) -> str:
    return _markdown_text("" if value is None else value).replace("\\", "\\\\").replace("|", "\\|")


__all__ = [
    "ConversationDocumentExporter",
    "MaterializedConversationDocument",
    "SemanticDocumentStore",
]
