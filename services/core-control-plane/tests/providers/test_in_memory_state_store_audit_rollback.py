"""All-or-nothing audited writes in the in-memory StateStore test double."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _FailingAuditStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_audit = False

    def _append_audit_locked(self, entry: Mapping[str, Any]) -> None:
        if self.fail_audit:
            raise RuntimeError("audit append failed")
        super()._append_audit_locked(entry)


async def test_failed_audit_restores_existing_row_value_and_newest_first_order() -> None:
    store = _FailingAuditStore()
    for key in ("a", "b", "c"):
        await store.write_state(key, {"revision": 1, "value": key})
    store.fail_audit = True

    with pytest.raises(RuntimeError, match="audit append failed"):
        await store.compare_and_set_state_with_audit(
            "a",
            {"revision": 2, "value": "changed"},
            expected_revision=1,
            audit_entry={"kind": "test"},
        )

    assert await store.read_state("a") == {"revision": 1, "value": "a"}
    newest_first = [row["value"] for row in await store.read_states("", limit=10)]
    assert newest_first == ["c", "b", "a"]
    assert list(store.audit_entries) == []


async def test_failed_audit_removes_a_new_row_and_keeps_existing_rows() -> None:
    store = _FailingAuditStore()
    await store.write_state("kept", {"revision": 1})
    store.fail_audit = True

    with pytest.raises(RuntimeError, match="audit append failed"):
        await store.write_state_with_audit_if_absent("new", {"revision": 1}, {"kind": "test"})

    assert await store.read_state("new") is None
    assert await store.read_state("kept") == {"revision": 1}
