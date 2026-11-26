from __future__ import annotations

import pytest
from fdai.core.case_history.dual_write import DualWriteCaseHistoryMetadataStore
from fdai.core.case_history.testing import InMemoryCaseHistoryMetadataStore
from tests.persistence.test_state_store_case_history import _record


async def test_reads_stay_on_legacy_authority_before_cutover() -> None:
    authority = InMemoryCaseHistoryMetadataStore()
    shadow = InMemoryCaseHistoryMetadataStore()
    record = _record()
    await authority.append_revision(record)
    store = DualWriteCaseHistoryMetadataStore(authority=authority, shadow=shadow)
    assert (
        await store.latest(record.case_id, access_scope_digest=record.access_scope_digest) == record
    )
    assert (
        await shadow.latest(record.case_id, access_scope_digest=record.access_scope_digest) is None
    )


async def test_authority_is_not_committed_when_shadow_append_fails() -> None:
    authority = InMemoryCaseHistoryMetadataStore()

    class _FailOnce(InMemoryCaseHistoryMetadataStore):
        failed = False

        async def append_revision(self, record):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise RuntimeError("shadow unavailable")
            return await super().append_revision(record)

    shadow = _FailOnce()
    store = DualWriteCaseHistoryMetadataStore(authority=authority, shadow=shadow)
    record = _record()
    with pytest.raises(RuntimeError, match="shadow unavailable"):
        await store.append_revision(record)
    assert (
        await authority.latest(record.case_id, access_scope_digest=record.access_scope_digest)
        is None
    )
    assert await store.append_revision(record) is True
    assert await authority.latest(
        record.case_id, access_scope_digest=record.access_scope_digest
    ) == await shadow.latest(record.case_id, access_scope_digest=record.access_scope_digest)
