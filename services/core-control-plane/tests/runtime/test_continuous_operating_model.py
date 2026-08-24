from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.continuous_operating_model import (
    OPERATING_MODEL_CURSOR_KEY,
    OPERATING_MODEL_REJECTION_KEY,
    ContinuousOperatingModelWorker,
    project_initial_operating_model_from_env,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot, OperatingModelUpdate
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]


def _worker() -> tuple[
    ContinuousOperatingModelWorker,
    InMemoryOntologyInstanceStore,
    InMemoryStateStore,
]:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    state_store = InMemoryStateStore()
    worker = ContinuousOperatingModelWorker(
        provider=None,  # type: ignore[arg-type] - apply_update does not consume the provider
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        state_store=state_store,
        resource_lock=ResourceLockManager(),
    )
    return worker, store, state_store


class _BlockingOldSnapshotStore(InMemoryOntologyInstanceStore):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.old_projection_started = asyncio.Event()
        self.release_old_projection = asyncio.Event()

    async def replace_subgraph(self, **kwargs: Any) -> None:
        objects = kwargs["objects"]
        if objects and objects[0].id == "stale":
            self.old_projection_started.set()
            await self.release_old_projection.wait()
        await super().replace_subgraph(**kwargs)


class _FailCursorOnceStateStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_cursor_once = True

    async def write_state(self, key: str, value: dict[str, object]) -> None:
        if key == OPERATING_MODEL_CURSOR_KEY and self.fail_cursor_once:
            self.fail_cursor_once = False
            raise RuntimeError("injected cursor write failure")
        await super().write_state(key, value)


def _update(*, cursor: str, sequence: int, revision: str, identifier: str) -> OperatingModelUpdate:
    return OperatingModelUpdate(
        cursor=cursor,
        sequence=sequence,
        snapshot=OperatingModelSnapshot(
            source_revision=revision,
            objects=(
                OntologyObjectRecord(
                    id=identifier,
                    object_type="Resource",
                    properties={"id": identifier, "type": "app-service"},
                ),
            ),
            links=(),
        ),
    )


async def test_continuous_worker_projects_newer_snapshot_and_suppresses_duplicate() -> None:
    worker, store, state_store = _worker()
    update = _update(cursor="cursor-1", sequence=1, revision="revision-1", identifier="one")

    assert await worker.apply_update(update) is True
    assert await worker.apply_update(update) is False
    assert await store.get_object("one") is not None
    assert await state_store.read_state(OPERATING_MODEL_CURSOR_KEY) == {
        "schema_version": "1.0.0",
        "cursor": "cursor-1",
        "sequence": 1,
        "source_revision": "revision-1",
    }


async def test_continuous_worker_rejects_out_of_order_without_graph_change() -> None:
    worker, store, state_store = _worker()
    assert await worker.apply_update(
        _update(cursor="cursor-2", sequence=2, revision="revision-2", identifier="current")
    )

    applied = await worker.apply_update(
        _update(cursor="cursor-1", sequence=1, revision="revision-1", identifier="stale")
    )

    assert applied is False
    assert await store.get_object("current") is not None
    assert await store.get_object("stale") is None
    rejection = await state_store.read_state(OPERATING_MODEL_REJECTION_KEY)
    assert rejection is not None
    assert rejection["reason"] == "sequence_not_monotonic"


async def test_continuous_worker_rejects_changed_content_under_same_revision() -> None:
    worker, store, state_store = _worker()
    assert await worker.apply_update(
        _update(cursor="cursor-1", sequence=1, revision="revision-1", identifier="current")
    )

    applied = await worker.apply_update(
        _update(cursor="cursor-2", sequence=2, revision="revision-1", identifier="changed")
    )

    assert applied is False
    assert await store.get_object("current") is not None
    assert await store.get_object("changed") is None
    rejection = await state_store.read_state(OPERATING_MODEL_REJECTION_KEY)
    assert rejection is not None
    assert rejection["reason"] == "source_revision_reused"


async def test_continuous_worker_rejects_nonconsecutive_revision_reuse() -> None:
    worker, store, state_store = _worker()
    assert await worker.apply_update(
        _update(cursor="cursor-1", sequence=1, revision="revision-1", identifier="first")
    )
    assert await worker.apply_update(
        _update(cursor="cursor-2", sequence=2, revision="revision-2", identifier="current")
    )

    applied = await worker.apply_update(
        _update(cursor="cursor-3", sequence=3, revision="revision-1", identifier="changed")
    )

    assert applied is False
    assert await store.get_object("current") is not None
    assert await store.get_object("changed") is None
    rejection = await state_store.read_state(OPERATING_MODEL_REJECTION_KEY)
    assert rejection is not None
    assert rejection["reason"] == "source_revision_reused"


async def test_continuous_worker_closes_cursor_after_claimed_apply_interruption() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    state_store = _FailCursorOnceStateStore()
    worker = ContinuousOperatingModelWorker(
        provider=None,  # type: ignore[arg-type] - apply_update does not consume the provider
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        state_store=state_store,
        resource_lock=ResourceLockManager(),
    )
    update = _update(
        cursor="cursor-1",
        sequence=1,
        revision="revision-1",
        identifier="current",
    )

    with pytest.raises(RuntimeError, match="injected cursor write failure"):
        await worker.apply_update(update)
    projected = await store.get_object("current")
    assert projected is not None
    assert projected.revision == 1

    assert await worker.apply_update(update) is True
    recovered = await store.get_object("current")
    assert recovered is not None
    assert recovered.revision == 1
    assert await state_store.read_state(OPERATING_MODEL_CURSOR_KEY) == {
        "schema_version": "1.0.0",
        "cursor": "cursor-1",
        "sequence": 1,
        "source_revision": "revision-1",
    }


async def test_continuous_workers_serialize_overlapping_revisions() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = _BlockingOldSnapshotStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    state_store = InMemoryStateStore()
    resource_lock = ResourceLockManager()
    workers = tuple(
        ContinuousOperatingModelWorker(
            provider=None,  # type: ignore[arg-type] - apply_update does not consume the provider
            store=store,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
            state_store=state_store,
            resource_lock=resource_lock,
        )
        for _ in range(2)
    )

    stale_task = asyncio.create_task(
        workers[0].apply_update(
            _update(cursor="cursor-1", sequence=1, revision="revision-1", identifier="stale")
        )
    )
    await store.old_projection_started.wait()
    current_task = asyncio.create_task(
        workers[1].apply_update(
            _update(cursor="cursor-2", sequence=2, revision="revision-2", identifier="current")
        )
    )
    await asyncio.sleep(0)
    assert current_task.done() is False

    store.release_old_projection.set()
    assert await stale_task is True
    assert await current_task is True
    assert await store.get_object("stale") is None
    assert await store.get_object("current") is not None
    assert await state_store.read_state(OPERATING_MODEL_CURSOR_KEY) == {
        "schema_version": "1.0.0",
        "cursor": "cursor-2",
        "sequence": 2,
        "source_revision": "revision-2",
    }


async def test_new_replica_bootstrap_cannot_overwrite_continuous_revision(
    tmp_path: Path,
) -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    state_store = InMemoryStateStore()
    resource_lock = ResourceLockManager()
    worker = ContinuousOperatingModelWorker(
        provider=None,  # type: ignore[arg-type] - apply_update does not consume the provider
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        state_store=state_store,
        resource_lock=resource_lock,
    )
    assert await worker.apply_update(
        _update(cursor="cursor-2", sequence=2, revision="revision-2", identifier="current")
    )
    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [
                    {
                        "id": "stale",
                        "object_type": "Resource",
                        "properties": {"id": "stale", "type": "app-service"},
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    result = await project_initial_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        state_store=state_store,
        environment={"FDAI_OPERATING_MODEL_PATH": str(path)},
        resource_lock=resource_lock,
    )

    assert result is None
    assert await store.get_object("current") is not None
    assert await store.get_object("stale") is None
    assert await state_store.read_state(OPERATING_MODEL_CURSOR_KEY) == {
        "schema_version": "1.0.0",
        "cursor": "cursor-2",
        "sequence": 2,
        "source_revision": "revision-2",
    }
