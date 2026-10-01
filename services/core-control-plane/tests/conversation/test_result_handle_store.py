"""Threat-review tests for Core-owned result handle storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.result_handle_store import (
    InMemoryResultHandleStore,
    ResultHandleBinding,
    ResultHandleGetStatus,
    ResultHandleKey,
    StaticResultHandleKeyProvider,
    reauthorize_result_handle_rows,
    rendered_order_digest,
)
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

NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def _key(version: str = "result-handle-key-v1", fill: int = 1) -> ResultHandleKey:
    return ResultHandleKey(version, bytes([fill]) * 32)


def _row(index: int) -> TypedRowKey:
    return TypedRowKey(row_type="semantic_query_row", row_digest=content_digest({"row": index}))


def _handle(*, rows: tuple[TypedRowKey, ...] | None = None) -> ResultHandle:
    row_keys = rows or (_row(1), _row(2))
    return ResultHandle.model_validate(
        {
            "deployment_scope_digest": DIGEST_A,
            "principal_digest": DIGEST_B,
            "conversation_id": "conversation-1",
            "purpose": "operations-review",
            "manifest_digest": DIGEST_C,
            "rendered_order_digest": rendered_order_digest(row_keys),
            "row_keys": row_keys,
            "sort": (SortTerm(field_name="rendered_order", direction=SortDirection.ASC),),
            "page": PageDescriptor(page_number=1, page_size=len(row_keys)),
            "truncated": False,
            "snapshot_cells": (
                SnapshotRow(
                    row_key=row_keys[0],
                    cells=(SnapshotCell(field_name="name", value_digest=DIGEST_D),),
                ),
            ),
        },
        context={"allowed_snapshot_fields": {"name"}},
    )


def _binding(**updates: object) -> ResultHandleBinding:
    values = {
        "deployment_scope_digest": DIGEST_A,
        "principal_digest": DIGEST_B,
        "conversation_id": "conversation-1",
        "purpose": "operations-review",
        "manifest_digest": DIGEST_C,
        "now": NOW + timedelta(minutes=1),
    }
    values.update(updates)
    return ResultHandleBinding(**values)


def _store(
    *,
    current: ResultHandleKey | None = None,
    previous: ResultHandleKey | None = None,
    handle_ref: str = "OpaqueHandleRef0123456789abcdefABCDEF",
) -> InMemoryResultHandleStore:
    return InMemoryResultHandleStore(
        keys=StaticResultHandleKeyProvider(current=current or _key(), previous=previous),
        handle_ref_factory=lambda: handle_ref,
    )


@pytest.mark.asyncio
async def test_store_round_trip_returns_bound_handle_and_random_opaque_ref() -> None:
    store = _store()
    handle = _handle()

    ref = await store.put(handle, issued_at=NOW, expires_at=NOW + timedelta(minutes=15))
    loaded = await store.get(ref, binding=_binding(), allowed_snapshot_fields={"name"})

    assert ref.handle_ref == "OpaqueHandleRef0123456789abcdefABCDEF"
    assert loaded.status is ResultHandleGetStatus.BOUND
    assert loaded.handle == handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"conversation_id": "conversation-2"},
        {"principal_digest": "sha256:" + "0" * 64},
        {"deployment_scope_digest": "sha256:" + "1" * 64},
        {"purpose": "other-purpose"},
        {"manifest_digest": "sha256:" + "2" * 64},
    ],
)
async def test_cross_binding_fields_return_foreign(updates: dict[str, object]) -> None:
    store = _store()
    ref = await store.put(_handle(), issued_at=NOW, expires_at=NOW + timedelta(minutes=15))

    loaded = await store.get(ref, binding=_binding(**updates), allowed_snapshot_fields={"name"})

    assert loaded.status is ResultHandleGetStatus.FOREIGN
    assert loaded.handle is None


@pytest.mark.asyncio
async def test_unknown_tampered_expired_and_deleted_references_fail_closed() -> None:
    store = _store()
    ref = await store.put(_handle(), issued_at=NOW, expires_at=NOW + timedelta(minutes=15))

    unknown = ref.model_copy(update={"handle_ref": "UnknownHandleRef0123456789abcdefABCD"})
    tampered = ref.model_copy(update={"key_version": "result-handle-key-v9"})
    expired = ref.model_copy(update={"expires_at": NOW + timedelta(seconds=1)})

    assert (
        await store.get(unknown, binding=_binding(), allowed_snapshot_fields={"name"})
    ).status is (ResultHandleGetStatus.UNAVAILABLE)
    assert (
        await store.get(tampered, binding=_binding(), allowed_snapshot_fields={"name"})
    ).status is (ResultHandleGetStatus.UNAVAILABLE)
    assert (
        await store.get(
            expired,
            binding=_binding(now=NOW + timedelta(seconds=2)),
            allowed_snapshot_fields={"name"},
        )
    ).status is ResultHandleGetStatus.EXPIRED
    assert (
        await store.delete_conversation(
            deployment_scope_digest=DIGEST_A, conversation_id="conversation-1"
        )
        == 1
    )
    assert (await store.get(ref, binding=_binding(), allowed_snapshot_fields={"name"})).status is (
        ResultHandleGetStatus.UNAVAILABLE
    )


def test_secured_reread_drops_rows_the_principal_can_no_longer_read() -> None:
    first, second = _row(1), _row(2)
    handle = _handle(rows=(first, second))

    reauthorized = reauthorize_result_handle_rows(handle, readable_rows=(second,))

    assert reauthorized.row_keys == (second,)
    assert reauthorized.snapshot_cells == ()
    assert reauthorized.rendered_order_digest == rendered_order_digest((second,))


@pytest.mark.asyncio
async def test_snapshot_cells_require_allowlisted_fields_on_load() -> None:
    store = _store()
    ref = await store.put(_handle(), issued_at=NOW, expires_at=NOW + timedelta(minutes=15))

    assert (
        await store.get(ref, binding=_binding(), allowed_snapshot_fields={"name"})
    ).status is ResultHandleGetStatus.BOUND
    assert (
        await store.get(ref, binding=_binding(), allowed_snapshot_fields={"sku"})
    ).status is ResultHandleGetStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_key_rotation_keeps_previous_key_for_decryption_only() -> None:
    old_store = _store(current=_key("result-handle-key-v1", 1))
    ref = await old_store.put(_handle(), issued_at=NOW, expires_at=NOW + timedelta(minutes=15))
    rotated = InMemoryResultHandleStore(
        keys=StaticResultHandleKeyProvider(
            current=_key("result-handle-key-v2", 2),
            previous=_key("result-handle-key-v1", 1),
        ),
        handle_ref_factory=lambda: "OtherOpaqueHandleRef0123456789abcdef",
    )
    rotated._records = old_store._records  # test-only restart over retained encrypted storage

    loaded = await rotated.get(ref, binding=_binding(), allowed_snapshot_fields={"name"})
    new_ref = await rotated.put(_handle(), issued_at=NOW, expires_at=NOW + timedelta(minutes=15))

    assert loaded.status is ResultHandleGetStatus.BOUND
    assert new_ref.key_version == "result-handle-key-v2"


def test_rendered_order_digest_matches_console_fixture_order() -> None:
    console_rows = (_row(2), _row(1), _row(3))

    handle = _handle(rows=console_rows)

    assert handle.rendered_order_digest == rendered_order_digest(console_rows)
    assert handle.rendered_order_digest != rendered_order_digest(
        tuple(sorted(console_rows, key=str))
    )
