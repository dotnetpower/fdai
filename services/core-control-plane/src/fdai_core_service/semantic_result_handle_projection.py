"""Project verified semantic answer rows into Core result-handle records."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.conversation.result_handle_store import ResultHandleStore, rendered_order_digest
from fdai.core.conversation.semantic_stored_result_handles import StoredReferenceContext
from fdai_service_contracts import SemanticTurnDisposition, SemanticTurnRequest
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import (
    PageDescriptor,
    ResultHandle,
    SnapshotCell,
    SnapshotRow,
    SortDirection,
    SortTerm,
    TypedRowKey,
)
from fdai_service_contracts.semantic_turn import SemanticTurnResult

_SNAPSHOT_FIELDS = frozenset(
    {
        "name",
        "revision_name",
        "ready_revision_name",
        "running_status",
        "source_observed_at",
        "inventory_read_at",
        "provisioning_status",
        "type",
        "status",
        "location",
    }
)


def result_handle_from_technical_details(
    request: SemanticTurnRequest,
    result: SemanticTurnResult,
    *,
    technical_details: Mapping[str, object],
) -> ResultHandle | None:
    """Build a result handle from verified rendered table rows, when present."""

    outputs = technical_details.get("outputs")
    if (
        result.disposition is not SemanticTurnDisposition.ANSWERED
        or result.ontology_release_digest is None
        or result.principal_manifest_digest is None
        or not isinstance(outputs, list)
    ):
        return None
    row_keys: list[TypedRowKey] = []
    row_identities: list[str] = []
    snapshot_rows: list[SnapshotRow] = []
    for output in outputs:
        if isinstance(output, Mapping):
            _append_output_rows(
                output,
                row_keys=row_keys,
                row_identities=row_identities,
                snapshot_rows=snapshot_rows,
            )
    if not row_keys:
        return None
    ordered = tuple(row_keys[:1000])
    ordered_identities = tuple(row_identities[:1000])
    ordered_json = {item.model_dump_json() for item in ordered}
    return ResultHandle.model_validate(
        {
            "deployment_scope_digest": result.ontology_release_digest,
            "principal_digest": result.principal_manifest_digest,
            "conversation_id": request.session_id,
            "purpose": request.purpose,
            "manifest_digest": result.principal_manifest_digest,
            "rendered_order_digest": rendered_order_digest(ordered),
            "row_keys": ordered,
            "row_identities": ordered_identities,
            "sort": (SortTerm(field_name="rendered_order", direction=SortDirection.ASC),),
            "page": PageDescriptor(page_number=1, page_size=len(ordered)),
            "truncated": len(row_keys) > len(ordered),
            "snapshot_cells": tuple(
                row for row in snapshot_rows if row.row_key.model_dump_json() in ordered_json
            ),
        },
        context={"allowed_snapshot_fields": _SNAPSHOT_FIELDS},
    )


def _append_output_rows(
    output: Mapping[str, object],
    *,
    row_keys: list[TypedRowKey],
    row_identities: list[str],
    snapshot_rows: list[SnapshotRow],
) -> None:
    node_id = output.get("node_id")
    rows = output.get("rows")
    if not isinstance(node_id, str) or not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_id = row.get("row_id")
        values = row.get("values")
        if not isinstance(row_id, str) or not isinstance(values, Mapping):
            continue
        key = TypedRowKey(
            row_type="semantic_query_row",
            row_digest=content_digest({"row_id": row_id}),
        )
        row_keys.append(key)
        row_identities.append(row_id)
        cells = tuple(
            SnapshotCell(field_name=field, value_digest=content_digest({"value": value}))
            for field, value in values.items()
            if isinstance(field, str) and field in _SNAPSHOT_FIELDS
        )
        if cells:
            snapshot_rows.append(SnapshotRow(row_key=key, cells=cells))


def stored_reference_arguments(
    request: SemanticTurnRequest, *, enabled: bool, store: ResultHandleStore | None
) -> dict[str, StoredReferenceContext]:
    """Return the runtime keyword carrying stored references, only when handles are on."""

    if not (enabled and store is not None and request.recent_result_handles):
        return {}
    context = StoredReferenceContext(request.session_id, request.recent_result_handles, store)
    return {"stored_reference_context": context}


__all__ = ["result_handle_from_technical_details", "stored_reference_arguments"]
