from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.operational_context import OPERATING_INTENT_SOURCE_ADMISSION_KEY as KEY
from fdai.delivery.persistence.postgres_forecast_change_window_history import _admission_history
from fdai.runtime.change_window_history import (
    CHANGE_WINDOW_ADMISSION_HISTORY_PREFIX as PREFIX,
)
from fdai.runtime.change_window_history import persist_change_window_admission
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing import InMemoryStateStore
from tests.runtime.test_change_window_history import NOW, _window
from tests.runtime.test_operating_intent_revalidation import (
    _RETRIEVED_AT,
    _catalog_and_store,
    _document,
    _runtime,
    _write,
)


def admission(*, minute: int = 0, revision: str = "intent-rev-1") -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "status": "admitted",
        "binding_generation": 1,
        "source_revision": revision,
        "snapshot_digest": "sha256:" + ("1" if revision == "intent-rev-1" else "2") * 64,
        "owned_object_ids": ["window-1"],
        "validated_at": (NOW + timedelta(minutes=minute)).isoformat(),
        "max_age_seconds": 900,
    }


async def persist(
    store: StateStore,
    *,
    minute: int = 0,
    status: str = "admitted",
    revision: str = "intent-rev-1",
    windows: tuple[OntologyObjectRecord, ...] = (),
) -> bool:
    value = {**admission(minute=minute, revision=revision), "status": status}
    return await persist_change_window_admission(
        store,
        key=KEY,
        admission=value,
        current=await store.read_state(KEY),
        snapshot=OperatingModelSnapshot(revision, windows, ()) if status == "admitted" else None,
        source_revision=revision,
        document_digest=str(value["snapshot_digest"]),
        recorded_at=NOW + timedelta(minutes=minute),
    )


async def retained(store: StateStore) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    current = await store.read_state(KEY)
    assert current is not None
    history = await store.read_state(str(current["history_ref"]))
    assert history is not None
    return current, history


async def test_full_snapshot_revalidation_and_exact_retry_are_retained() -> None:
    store = InMemoryStateStore()
    windows = (_window("window-1", start=0, end=30),)
    assert await persist(store, windows=windows)
    first, first_entry = await retained(store)
    assert first["revision"] == 1 and first_entry["previous_ref"] is None
    assert first_entry["windows"][0]["recorded_at"] == NOW.isoformat()
    assert await persist(store, windows=windows)
    assert await retained(store) == (first, first_entry)
    assert await persist(store, minute=1, windows=windows)
    second, second_entry = await retained(store)
    assert second["revision"] == 2
    assert second_entry["previous_ref"] == first["history_ref"]
    assert second_entry["snapshot_ref"] == first["history_ref"]
    assert second_entry["windows"] is None
    assert second_entry["recorded_at"] == (NOW + timedelta(minutes=1)).isoformat()
    assert len((await store.read_audit_entries(limit=10))[0]) == 2


async def test_re_admission_of_old_document_keeps_new_record_time_and_chain() -> None:
    store = InMemoryStateStore()
    for minute, revision in enumerate(("intent-rev-1", "intent-rev-2", "intent-rev-1")):
        assert await persist(
            store,
            minute=minute,
            revision=revision,
            windows=(_window("window-1", start=1 if minute == 1 else 0, end=30),),
        )
    current, entry = await retained(store)
    assert current["revision"] == 3
    assert entry["recorded_at"] == (NOW + timedelta(minutes=2)).isoformat()
    assert entry["windows"][0]["effective_from"] == NOW.isoformat()
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 3


@pytest.mark.parametrize("status", ["quarantined", "unavailable"])
async def test_denial_is_retained_not_relabelled_as_an_empty_admission(status: str) -> None:
    store = InMemoryStateStore()
    assert await persist(store, windows=(_window("window-1", start=0, end=30),))
    prior, _ = await retained(store)
    assert await persist(store, minute=1, status=status)
    current, entry = await retained(store)
    assert current["status"] == status
    assert entry["admission"]["status"] == status
    assert entry["windows"] == []
    assert entry["previous_ref"] == prior["history_ref"]
    read = _admission_history(
        str(current["history_ref"]),
        entry,
        subject_ref="resource-example",
        start_at=NOW,
        end_at=NOW,
        known_at=NOW + timedelta(minutes=2),
    )
    assert read.source_status == status and not read.rows


async def test_removed_window_is_explicit_in_full_successor_snapshot() -> None:
    store = InMemoryStateStore()
    first = (_window("window-1", start=0, end=30), _window("window-2", start=0, end=30))
    assert await persist(store, windows=first)
    prior, original = await retained(store)
    assert await persist(store, minute=1, revision="intent-rev-2", windows=first[1:])
    _, successor = await retained(store)
    assert successor["previous_ref"] == prior["history_ref"]
    assert [item["window_id"] for item in original["windows"]] == ["window-1", "window-2"]
    assert [item["window_id"] for item in successor["windows"]] == ["window-2"]


async def test_legacy_admission_starts_an_unanchored_chain_without_retroactive_history() -> None:
    store = InMemoryStateStore()
    await store.write_state(KEY, admission())
    assert await persist(store, minute=1)
    current, entry = await retained(store)
    assert current["revision"] == 1 and entry["previous_ref"] is None
    assert entry["recorded_at"] != NOW.isoformat()


async def test_losing_cas_leaves_no_history_or_audit() -> None:
    store = InMemoryStateStore()
    assert await persist(store)
    stale = await store.read_state(KEY)
    assert await persist(store, minute=1, status="quarantined")
    assert not await persist_change_window_admission(
        store,
        key=KEY,
        admission=admission(minute=2),
        current=stale,
        snapshot=OperatingModelSnapshot("intent-rev-1", (), ()),
        source_revision="intent-rev-1",
        document_digest="sha256:" + "1" * 64,
        recorded_at=NOW + timedelta(minutes=2),
    )
    assert (await retained(store))[0]["status"] == "quarantined"
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 2
    assert len((await store.read_audit_entries(limit=10))[0]) == 2


async def test_audit_failure_rolls_back_admission_and_snapshot() -> None:
    class FailingAudit(InMemoryStateStore):
        fail = False

        def _append_audit_locked(self, entry: Mapping[str, Any]) -> None:
            if self.fail:
                raise OSError("injected audit failure")
            super()._append_audit_locked(entry)

    store = FailingAudit()
    assert await persist(store)
    prior = await retained(store)
    store.fail = True
    with pytest.raises(OSError, match="injected"):
        await persist(store, minute=1)
    assert await retained(store) == prior
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 1
    assert len((await store.read_audit_entries(limit=10))[0]) == 1


async def test_response_loss_after_commit_is_idempotent_on_retry() -> None:
    class ResponseLoss(InMemoryStateStore):
        lose = True

        async def write_state_pair_with_audit_if_absent(self, *args: Any, **kwargs: Any) -> bool:
            result = await super().write_state_pair_with_audit_if_absent(*args, **kwargs)
            if self.lose:
                self.lose = False
                raise OSError("injected response loss")
            return result

    store = ResponseLoss()
    with pytest.raises(OSError, match="response loss"):
        await persist(store)
    committed = await retained(store)
    assert await persist(store)
    assert await retained(store) == committed
    assert len((await store.read_audit_entries(limit=10))[0]) == 1


async def test_cancellation_is_not_an_admission() -> None:
    class CancelledStore(InMemoryStateStore):
        async def write_state_pair_with_audit_if_absent(self, *args: Any, **kwargs: Any) -> bool:
            raise asyncio.CancelledError

    store = CancelledStore()
    with pytest.raises(asyncio.CancelledError):
        await persist(store)
    assert await store.read_state(KEY) is None
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 0


async def test_backdated_revalidation_cannot_replace_a_later_admission() -> None:
    store = InMemoryStateStore()
    assert await persist(store, minute=2)
    assert not await persist(store, minute=1)
    assert (await retained(store))[0]["revision"] == 1


@pytest.mark.parametrize("revision", [True, -1, "1", 1.0])
async def test_corrupt_revision_is_not_an_implicit_zero(revision: object) -> None:
    store = InMemoryStateStore()
    await store.write_state(KEY, {**admission(), "revision": revision})
    with pytest.raises(ValueError, match="revision"):
        await persist(store, minute=1)
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 0


async def test_actual_source_fences_departing_generation_before_projection_and_history(
    tmp_path: Path,
) -> None:
    catalog, graph = _catalog_and_store()
    store = InMemoryStateStore()
    document = _document()
    path = tmp_path / "source.json"
    _write(path, document)
    newer = _runtime(
        path=path,
        document=document,
        store=graph,
        catalog=catalog,
        state_store=store,
        FDAI_OPERATING_INTENT_SOURCE_GENERATION="2",
    )
    at = _RETRIEVED_AT + timedelta(minutes=1)
    assert await newer.admit(now=at) is not None
    before = await retained(store)
    manifest_before = await store.read_state("operating-intent-source:manifest")
    graph_before = await graph.get_object("change-window-1")
    departing_document = _document()
    departing_document["source_revision"] = "departing-revision"
    provenance = departing_document["provenance"]
    assert isinstance(provenance, dict)
    provenance["resolved_ref"] = "departing-revision"
    old_path = tmp_path / "old-source.json"
    _write(old_path, departing_document)
    departing = _runtime(
        path=old_path,
        document=departing_document,
        store=graph,
        catalog=catalog,
        state_store=store,
        FDAI_OPERATING_INTENT_SOURCE_GENERATION="1",
    )
    assert await departing.admit(now=at + timedelta(seconds=1)) is None
    assert await retained(store) == before
    assert await graph.get_object("change-window-1") == graph_before
    assert await store.read_state("operating-intent-source:manifest") == manifest_before
    assert (await store.read_state_page(PREFIX, limit=10))[1] == 1
