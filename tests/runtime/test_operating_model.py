from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.runtime.operating_model import project_operating_model_from_env
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _catalog_and_store() -> tuple[OntologyCatalog, InMemoryOntologyInstanceStore]:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    return catalog, store


async def test_runtime_projects_configured_operating_model(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-1",
                "objects": [
                    {
                        "id": "resource-example",
                        "object_type": "Resource",
                        "properties": {"id": "resource-example", "type": "app-service"},
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    result = await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={"FDAI_OPERATING_MODEL_PATH": str(path)},
    )

    assert result is not None
    assert result.source_revision == "revision-1"
    assert await store.get_object("resource-example") is not None
    assert await status_store.read_state("operating-model:status") == {
        "schema_version": "1.0.0",
        "status": "projected",
        "source_revision": "revision-1",
        "object_count": 1,
        "link_count": 0,
    }


async def test_runtime_records_unconfigured_operating_model() -> None:
    status_store = InMemoryStateStore()

    result = await project_operating_model_from_env(
        store=None,
        object_types=(),
        link_types=(),
        status_store=status_store,
        env={},
    )

    assert result is None
    assert await status_store.read_state("operating-model:status") == {
        "schema_version": "1.0.0",
        "status": "unconfigured",
    }


async def test_runtime_replacement_removes_stale_owned_objects(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-model.json"
    initial = {
        "source_revision": "revision-1",
        "objects": [
            {
                "id": identifier,
                "object_type": "Resource",
                "properties": {"id": identifier, "type": "app-service"},
            }
            for identifier in ("resource-old", "resource-keep")
        ],
        "links": [],
    }
    path.write_text(json.dumps(initial), encoding="utf-8")
    await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={"FDAI_OPERATING_MODEL_PATH": str(path)},
    )
    replacement = dict(initial)
    replacement["source_revision"] = "revision-2"
    replacement["objects"] = initial["objects"][1:]
    path.write_text(json.dumps(replacement), encoding="utf-8")

    await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={"FDAI_OPERATING_MODEL_PATH": str(path)},
    )

    assert await store.get_object("resource-old") is None
    assert await store.get_object("resource-keep") is not None
    manifest = await status_store.read_state("operating-model:manifest")
    assert manifest is not None
    assert manifest["object_ids"] == ["resource-keep"]

    await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={},
    )

    assert await store.get_object("resource-keep") is None
    assert await status_store.read_state("operating-model:status") == {
        "schema_version": "1.0.0",
        "status": "unconfigured",
    }


async def test_runtime_rejects_configured_model_without_store(tmp_path: Path) -> None:
    path = tmp_path / "operating-model.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="requires an ontology instance store"):
        await project_operating_model_from_env(
            store=None,
            object_types=(),
            link_types=(),
            env={"FDAI_OPERATING_MODEL_PATH": str(path)},
        )


async def test_runtime_accepts_bounded_applying_recovery_union() -> None:
    status_store = InMemoryStateStore()
    await status_store.write_state(
        "operating-model:manifest",
        {
            "schema_version": "1.0.0",
            "status": "applying",
            "source_revision": "revision-interrupted",
            "object_ids": [f"resource-{index}" for index in range(50_001)],
            "link_keys": [],
        },
    )

    result = await project_operating_model_from_env(
        store=None,
        object_types=(),
        link_types=(),
        status_store=status_store,
        env={},
    )

    assert result is None
    manifest = await status_store.read_state("operating-model:manifest")
    assert manifest is not None
    assert manifest["status"] == "unconfigured"


async def test_runtime_cleans_interrupted_union_before_new_projection(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-model.json"
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-interrupted",
                "objects": [
                    {
                        "id": "resource-interrupted",
                        "object_type": "Resource",
                        "properties": {
                            "id": "resource-interrupted",
                            "type": "app-service",
                        },
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={"FDAI_OPERATING_MODEL_PATH": str(path)},
    )
    await status_store.write_state(
        "operating-model:manifest",
        {
            "schema_version": "1.0.0",
            "status": "applying",
            "source_revision": "revision-interrupted",
            "object_ids": ["resource-interrupted"],
            "link_keys": [],
        },
    )
    path.write_text(
        json.dumps(
            {
                "source_revision": "revision-recovered",
                "objects": [
                    {
                        "id": "resource-current",
                        "object_type": "Resource",
                        "properties": {"id": "resource-current", "type": "app-service"},
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    await project_operating_model_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={"FDAI_OPERATING_MODEL_PATH": str(path)},
    )

    assert await store.get_object("resource-interrupted") is None
    assert await store.get_object("resource-current") is not None
    manifest = await status_store.read_state("operating-model:manifest")
    assert manifest is not None
    assert manifest["status"] == "projected"
    assert manifest["object_ids"] == ["resource-current"]
