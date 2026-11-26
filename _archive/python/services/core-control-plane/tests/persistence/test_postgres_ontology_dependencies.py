"""Exact dependency snapshots for staged ontology publication."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.delivery.persistence import postgres_ontology
from fdai.delivery.persistence.postgres_ontology_prepared import persist_replacement
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
)

from tests.persistence.test_postgres_ontology_instance import (
    _isolated_replacement_store,
    _review_object,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("dependency_kind", ["external", "removed"])
async def test_dependency_content_drift_without_revision_blocks_publication(
    monkeypatch: pytest.MonkeyPatch, dependency_kind: str
) -> None:
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("dependency", "ReviewCheck"))
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY, snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE, 'example-generation')"
            )

        async def persist(config, prepared):
            await persist_replacement(config, prepared)
            async with await store._connect() as connection:
                await connection.execute(
                    "UPDATE ontology_resource SET properties=jsonb_set(properties,"
                    "'{status}',to_jsonb('changed'::text)) WHERE id='dependency'"
                )

        monkeypatch.setattr(postgres_ontology, "persist_replacement", persist)
        with pytest.raises(OntologyInstanceValidationError, match="dependency revision changed"):
            await store.replace_subgraph_with_state(
                objects=(_review_object("new-case"),),
                links=(
                    OntologyLinkRecord(
                        link_type="contains_check", from_id="new-case", to_id="dependency"
                    ),
                )
                if dependency_kind == "external"
                else (),
                previous_object_ids=("dependency",) if dependency_kind == "removed" else (),
                previous_link_keys=(),
                state_updates={"example:publication": {"complete": True}},
                expected_active_generation="example-generation",
            )
        assert await store.get_object("new-case") is None
        dependency = await store.get_object("dependency")
        assert dependency is not None
        assert dependency.revision == 1
        assert dependency.properties["status"] == "changed"
        async with await store._connect() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM state_kv WHERE key='example:publication'"
            )
            assert await cursor.fetchone() is None


async def test_link_page_pins_external_endpoint_content_after_other_owner_changes():
    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("dependency", "ReviewCheck"))
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
        await store.replace_subgraph_with_state(
            objects=(_review_object("case"),),
            links=(
                OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="dependency"),
            ),
            previous_object_ids=(),
            previous_link_keys=(),
            state_updates={},
            expected_active_generation="example-generation",
        )
        digest = await store.pin_inventory_snapshot()
        before = await store.read_inventory_snapshot_page(
            snapshot_digest=digest, relationships=True
        )
        assert before.dependency_complete
        assert len(before.dependencies) == 1
        assert before.dependencies[0].properties["status"] == "open"
        await store.upsert_object(
            replace(
                _review_object("dependency", "ReviewCheck"),
                properties={"id": "dependency", "status": "changed"},
            ),
            expected_revision=1,
        )
        after = await store.read_inventory_snapshot_page(snapshot_digest=digest, relationships=True)
        assert after == before
        assert (await store.get_object("dependency")).revision == 2


@pytest.mark.parametrize(
    "defect",
    [
        "healthy",
        "legacy",
        "missing",
        "removed",
        "bool",
        "zero",
        "type",
        "properties",
        "extra",
        "owned",
    ],
)
def test_link_page_dependency_evidence_boundaries(defect):
    from fdai.delivery.persistence.postgres_ontology_snapshot import (
        _page_dependencies,
        _SnapshotIndex,
    )

    declaration = {
        "object_type": "ReviewCheck",
        "revision": 3,
        "type_version": "1.0.0",
        "catalog_digest": "sha256:" + "a" * 64,
        "properties": {"id": "dependency", "status": "open"},
    }
    dependencies = {"dependency": declaration}
    revisions = {"case": 1}
    if defect == "legacy":
        declaration.pop("properties")
    elif defect == "missing":
        dependencies = {}
    elif defect == "removed":
        dependencies = {"unrelated-removed": declaration}
    elif defect == "bool":
        declaration["revision"] = True
    elif defect == "zero":
        declaration["revision"] = 0
    elif defect == "type":
        declaration["object_type"] = ""
    elif defect == "properties":
        declaration["properties"] = []
    elif defect == "extra":
        declaration["authority"] = True
    elif defect == "owned":
        revisions["dependency"] = 3
        dependencies = {}
    index = _SnapshotIndex(
        None, "sha256:" + "b" * 64, {}, {"dependency_revisions": dependencies}, (), revisions
    )
    links = (OntologyLinkRecord(link_type="contains_check", from_id="case", to_id="dependency"),)
    if defect in {"bool", "zero", "type", "properties", "extra"}:
        with pytest.raises(OntologyInstanceValidationError, match="dependency is malformed"):
            _page_dependencies(index, links)
    else:
        records, complete = _page_dependencies(index, links)
        assert complete is (defect in {"healthy", "owned"})
        assert len(records) == (1 if defect == "healthy" else 0)


@pytest.mark.parametrize(
    "condition", ["healthy", "wrong_previous", "wrong_desired", "owner_drift", "claim_foreign"]
)
async def test_inventory_owner_sets_are_bound_independently_of_caller_lists(monkeypatch, condition):
    from psycopg.types.json import Jsonb

    async with _isolated_replacement_store() as store:
        await store.upsert_object(_review_object("owned"))
        await store.upsert_object(_review_object("foreign"))
        async with await store._connect() as connection:
            await connection.execute(
                "CREATE TABLE inventory_active (singleton BOOLEAN PRIMARY KEY,snapshot_id TEXT);"
                "INSERT INTO inventory_active VALUES (TRUE,'example-generation')"
            )
            await connection.execute(
                "INSERT INTO state_kv (key,value) VALUES ('inventory-ontology:manifest',%s)",
                (Jsonb({"object_ids": ["owned"], "link_keys": []}),),
            )
        original = postgres_ontology.persist_replacement

        async def change_owner(config, prepared):
            await original(config, prepared)
            if condition == "owner_drift":
                async with await store._connect() as connection:
                    await connection.execute(
                        "UPDATE state_kv SET value=value || %s "
                        "WHERE key='inventory-ontology:manifest'",
                        (Jsonb({"revision": "changed"}),),
                    )

        monkeypatch.setattr(postgres_ontology, "persist_replacement", change_owner)

        async def publish():
            identifier = "foreign" if condition == "claim_foreign" else "new"
            await store.replace_subgraph_with_state(
                objects=(
                    replace(_review_object(identifier), revision=1)
                    if condition == "claim_foreign"
                    else _review_object(identifier),
                ),
                links=(),
                previous_object_ids=("foreign",) if condition == "wrong_previous" else ("owned",),
                previous_link_keys=(),
                state_updates={
                    "inventory-ontology:manifest": {
                        "object_ids": ["other"] if condition == "wrong_desired" else [identifier],
                        "link_keys": [],
                    }
                },
                expected_active_generation="example-generation",
            )

        if condition == "healthy":
            await publish()
            assert await store.get_object("owned") is None
        else:
            with pytest.raises(OntologyInstanceValidationError, match="ownership"):
                await publish()
            assert await store.get_object("new") is None
        assert await store.get_object("foreign") is not None
