"""Materialize bounded document answers for verified semantic terminal projections."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    JsonObject,
)
from fdai_operator_service.families.conversation.document_export import (
    ConversationDocumentExporter,
)


def is_document_draft(projection: Mapping[str, object]) -> bool:
    """Return whether Core emitted one document action draft."""
    semantic = projection.get("semantic_result")
    if not isinstance(semantic, Mapping) or semantic.get("disposition") != "action_draft":
        return False
    assurance = semantic.get("assurance_observation")
    frame = assurance.get("frame") if isinstance(assurance, Mapping) else None
    subjects = frame.get("subject_types") if isinstance(frame, Mapping) else None
    return subjects == ["Document"]


def is_inventory_document(projection: Mapping[str, object]) -> bool:
    """Use only the Core-owned terminal presentation contract to attach a document."""
    semantic = projection.get("semantic_result")
    payload = projection.get("payload")
    if not isinstance(semantic, Mapping) or semantic.get("disposition") != "answered":
        return False
    details = payload.get("technical_details") if isinstance(payload, Mapping) else None
    context = details.get("presentation_context") if isinstance(details, Mapping) else None
    return (
        isinstance(context, Mapping)
        and context.get("operation") == "select"
        and context.get("output_shape") == "resource_list"
        and context.get("document_kind") == "inventory"
    )


def document_ready_answer(locale: str, *, included_rows: int, pdf_available: bool) -> str:
    """Render the verified document completion message."""
    formats = "Markdown 또는 PDF" if pdf_available else "Markdown"
    if locale.casefold().startswith("ko"):
        return (
            f"검증된 원본 조회의 전체 행 {included_rows}개를 포함한 문서를 만들었습니다. "
            f"미리보기의 범위와 제외 항목을 검토하거나 {formats}로 다운로드할 수 있습니다."
        )
    formats = "Markdown or PDF" if pdf_available else "Markdown"
    return (
        f"I created a document with all {included_rows} rows from the verified source query. "
        f"Review its scope and exclusions in the preview or download it as {formats}."
    )


def document_unavailable_answer(locale: str) -> str:
    """Render the fail-closed document unavailability message."""
    if locale.casefold().startswith("ko"):
        return (
            "전체 행을 검증할 수 없어 문서 다운로드를 만들지 않았습니다. "
            "근거의 완전성 또는 조회 한도를 확인한 후 범위를 좁혀 다시 요청해 주세요."
        )
    return (
        "No document download was created because the complete row set could not be verified. "
        "Check evidence completeness or query limits, then request a narrower scope."
    )


async def apply_document_answer(
    done: JsonObject,
    *,
    projection: Mapping[str, object],
    result_request_id: str,
    source_request_id: str | None,
    principal_id: str,
    locale: str,
    exporter: ConversationDocumentExporter | None,
) -> bool:
    """Replace one terminal answer with a verified document result when required."""
    inventory_document = is_inventory_document(projection)
    answer_replaced = inventory_document or is_document_draft(projection)
    if not answer_replaced:
        return False
    selected_request_id = result_request_id if inventory_document else source_request_id
    if exporter is None or selected_request_id is None:
        done["answer"] = document_unavailable_answer(locale)
        done["document_unavailable_reason"] = (
            "document_export_unavailable" if exporter is None else "document_source_not_found"
        )
        return True
    try:
        document = await exporter.materialize(
            principal_id=principal_id,
            source_request_id=selected_request_id,
        )
    except ConversationBoundaryError as exc:
        done["answer"] = document_unavailable_answer(locale)
        done["document_unavailable_reason"] = exc.code
        return True
    done["answer"] = document_ready_answer(
        locale,
        included_rows=document.included_rows,
        pdf_available=exporter.pdf_encoder is not None,
    )
    done["document_artifact"] = document.metadata(pdf_available=exporter.pdf_encoder is not None)
    return True
