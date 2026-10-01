"""Contract tests for ontology reasoning result handles and continuations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import (
    AggregatePushdown,
    EvidenceCompleteness,
    EvidenceManifest,
    EvidenceReference,
    KeysetCursor,
    LinkDirection,
    NextBatchDescriptor,
    OrderingTerm,
    PageDescriptor,
    QueryContinuation,
    ReasoningHandleCodecError,
    ReasoningHandleErrorCode,
    ResultHandle,
    ResultHandleRef,
    SnapshotCell,
    SnapshotRow,
    SortDirection,
    SortTerm,
    TypedPathPushdown,
    TypedRowKey,
    decode_reasoning_record,
    encode_reasoning_record,
    negotiate_write_version,
)
from pydantic import TypeAdapter, ValidationError

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
OPAQUE_REF = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def _row(index: int = 1) -> TypedRowKey:
    return TypedRowKey(row_type="resource", row_digest=content_digest({"row": index}))


def _handle_ref() -> ResultHandleRef:
    return ResultHandleRef(
        handle_ref=OPAQUE_REF,
        key_version="result-handle-key-v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )


def _result_handle(*, row_keys: tuple[TypedRowKey, ...] | None = None) -> ResultHandle:
    rows = (_row(),) if row_keys is None else row_keys
    return ResultHandle.model_validate(
        {
            "deployment_scope_digest": DIGEST_A,
            "principal_digest": DIGEST_B,
            "conversation_id": "conversation-1",
            "purpose": "operations-review",
            "manifest_digest": DIGEST_C,
            "rendered_order_digest": DIGEST_D,
            "row_keys": rows,
            "sort": (SortTerm(field_name="effective_at", direction=SortDirection.DESC),),
            "page": PageDescriptor(page_number=1, page_size=20),
            "truncated": False,
            "snapshot_cells": (
                SnapshotRow(
                    row_key=rows[0],
                    cells=(SnapshotCell(field_name="sku", value_digest=DIGEST_E),),
                ),
            ),
        },
        context={"allowed_snapshot_fields": {"sku"}},
    )


def _evidence_manifest() -> EvidenceManifest:
    return EvidenceManifest(
        cited_evidence=(
            EvidenceReference(evidence_ref="evidence:graph:1", receipt_digest=DIGEST_A),
        ),
        completeness=EvidenceCompleteness.COMPLETE,
        rows_digest=DIGEST_B,
    )


def _row_continuation() -> QueryContinuation:
    return QueryContinuation(
        deployment_scope_digest=DIGEST_A,
        principal_digest=DIGEST_B,
        conversation_id="conversation-1",
        purpose="operations-review",
        admitted_goal_digest=DIGEST_C,
        plan_digest=DIGEST_D,
        manifest_digest=DIGEST_E,
        query_version_digest=DIGEST_A,
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        cutoff=NOW + timedelta(seconds=1),
        ordering=(OrderingTerm(field_name="effective_at", direction=SortDirection.DESC),),
        keyset_cursor=KeysetCursor(
            cursor_digest=DIGEST_B,
            last_effective_at=NOW - timedelta(minutes=1),
            last_subject_digest=DIGEST_C,
        ),
        page_size=20,
        expires_at=NOW + timedelta(minutes=15),
        remaining_rows=7,
    )


def _batch_continuation() -> QueryContinuation:
    return QueryContinuation(
        deployment_scope_digest=DIGEST_A,
        principal_digest=DIGEST_B,
        conversation_id="conversation-1",
        purpose="operations-review",
        admitted_goal_digest=DIGEST_C,
        plan_digest=DIGEST_D,
        manifest_digest=DIGEST_E,
        query_version_digest=DIGEST_A,
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        cutoff=NOW + timedelta(seconds=1),
        ordering=(OrderingTerm(field_name="link_type", direction=SortDirection.ASC),),
        keyset_cursor=KeysetCursor(cursor_digest=DIGEST_B),
        page_size=20,
        expires_at=NOW + timedelta(minutes=15),
        remaining_batches=2,
        next_batch=NextBatchDescriptor(
            batch_id="batch-2",
            plan_digest=DIGEST_C,
            link_types=("runs_on",),
            depth_bound=2,
        ),
        listed_endpoint_digest=DIGEST_D,
    )


@pytest.mark.parametrize(
    "record",
    [
        _handle_ref(),
        _result_handle(),
        _evidence_manifest(),
        _row_continuation(),
        _batch_continuation(),
    ],
)
def test_contract_records_round_trip_through_canonical_json(record) -> None:
    encoded = encode_reasoning_record(record)
    context = {"allowed_snapshot_fields": {"sku"}} if isinstance(record, ResultHandle) else None

    decoded = decode_reasoning_record(type(record), encoded, validation_context=context)

    assert encode_reasoning_record(decoded) == encoded
    assert decoded == record


def test_pushdown_request_union_allows_aggregate_or_typed_path_only() -> None:
    adapter = TypeAdapter(AggregatePushdown | TypedPathPushdown)
    aggregate = adapter.validate_python({"kind": "aggregate", "operation": "count"})
    path = adapter.validate_python(
        {
            "kind": "typed_path",
            "link_types": ("runs_on", "depends_on"),
            "direction": LinkDirection.OUTGOING,
            "depth_bound": 3,
        }
    )

    assert isinstance(aggregate, AggregatePushdown)
    assert isinstance(path, TypedPathPushdown)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "text", "query": "free form"})


def test_n_and_n_minus_one_decode_are_supported() -> None:
    current = _handle_ref()
    previous_payload = {**current.model_dump(mode="json"), "schema_version": "1.0"}

    assert decode_reasoning_record(ResultHandleRef, encode_reasoning_record(current)) == current
    assert decode_reasoning_record(ResultHandleRef, previous_payload).schema_version == "1.0"


@pytest.mark.parametrize("version", ["0.9", "1.2", "2.0", "1.1.0", None])
def test_unsupported_versions_fail_with_stable_code(version) -> None:
    payload = {**_handle_ref().model_dump(mode="json"), "schema_version": version}

    with pytest.raises(ReasoningHandleCodecError) as exc_info:
        decode_reasoning_record(ResultHandleRef, payload)

    assert exc_info.value.code is ReasoningHandleErrorCode.UNSUPPORTED_SCHEMA_VERSION


def test_unknown_key_version_fails_with_stable_code() -> None:
    payload = {**_handle_ref().model_dump(mode="json"), "key_version": "result-handle-key-v9"}

    with pytest.raises(ReasoningHandleCodecError) as exc_info:
        decode_reasoning_record(ResultHandleRef, payload)

    assert exc_info.value.code is ReasoningHandleErrorCode.UNSUPPORTED_KEY_VERSION


@pytest.mark.parametrize(
    ("readers", "expected"),
    [
        ((("1.0",), ("1.0", "1.1")), "1.0"),
        ((("1.0", "1.1"), ("1.1",)), "1.1"),
        ((("1.0",), ("1.0",)), "1.0"),
        ((("1.1",), ("1.0", "1.1")), "1.1"),
    ],
)
def test_writer_negotiation_handles_rolling_upgrade_and_rollback(
    readers: tuple[tuple[str, ...], ...],
    expected: str,
) -> None:
    assert negotiate_write_version(readers) == expected


def test_writer_negotiation_rejects_no_common_supported_version() -> None:
    with pytest.raises(ReasoningHandleCodecError) as exc_info:
        negotiate_write_version((("1.0",), ("1.2",)))

    assert exc_info.value.code is ReasoningHandleErrorCode.INCOMPATIBLE_READER_VERSIONS


@pytest.mark.parametrize(
    "handle_ref",
    [
        "handle:meaningful-reference",
        "00000000-0000-0000-0000-000000000000",
        "short",
    ],
)
def test_opaque_reference_validation_rejects_embedded_meaning(handle_ref: str) -> None:
    with pytest.raises(ValidationError, match="opaque"):
        ResultHandleRef.model_validate(
            {**_handle_ref().model_dump(mode="json"), "handle_ref": handle_ref}
        )


def test_expiry_and_cutoff_validation_require_forward_aware_times() -> None:
    with pytest.raises(ValidationError, match="expires_at"):
        ResultHandleRef.model_validate(
            {
                **_handle_ref().model_dump(mode="json"),
                "expires_at": NOW - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        ResultHandleRef.model_validate(
            {**_handle_ref().model_dump(mode="json"), "issued_at": datetime(2026, 10, 1)}
        )
    with pytest.raises(ValidationError, match="expires_at"):
        QueryContinuation.model_validate(
            {
                **_row_continuation().model_dump(mode="json"),
                "expires_at": NOW,
            }
        )


def test_row_keys_are_bounded_and_unique() -> None:
    duplicate = (_row(), _row())
    with pytest.raises(ValidationError, match="row_keys"):
        _result_handle(row_keys=duplicate)

    too_many = tuple(
        TypedRowKey(row_type="resource", row_digest=content_digest({"row": index}))
        for index in range(1_001)
    )
    with pytest.raises(ValidationError):
        _result_handle(row_keys=too_many)


def test_snapshot_cells_are_restricted_to_validation_allowlist() -> None:
    payload = _result_handle().model_dump(mode="json")

    assert ResultHandle.model_validate(
        payload, context={"allowed_snapshot_fields": {"sku"}}
    ).snapshot_cells
    with pytest.raises(ValidationError, match="allowlist"):
        ResultHandle.model_validate(payload, context={"allowed_snapshot_fields": {"name"}})
    with pytest.raises(ValidationError, match="requires"):
        ResultHandle.model_validate(payload)


def test_continuation_progress_accounts_are_mutually_exclusive() -> None:
    assert _row_continuation().remaining_rows == 7
    assert _batch_continuation().remaining_batches == 2

    with pytest.raises(ValidationError, match="exactly one progress account"):
        QueryContinuation.model_validate(
            {
                **_row_continuation().model_dump(mode="json"),
                "remaining_batches": 1,
                "next_batch": _batch_continuation().next_batch,
                "listed_endpoint_digest": DIGEST_D,
            }
        )
    with pytest.raises(ValidationError, match="batch continuation requires"):
        QueryContinuation.model_validate(
            {
                **_row_continuation().model_dump(mode="json"),
                "remaining_rows": None,
                "remaining_batches": 1,
            }
        )
