"""Integration tests for the PostgreSQL ontology instance graph."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[2]


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _type(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )


def _store() -> PostgresOntologyInstanceStore:
    return PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=_requires_live_db()),
        object_types=(_type("ReviewCase"), _type("ReviewCheck")),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="contains_check",
                version="1.0.0",
                from_type="ReviewCase",
                to_type="ReviewCheck",
                cardinality=LinkCardinality.ONE_TO_MANY,
            ),
        ),
    )


async def test_postgres_ontology_round_trip_and_traversal() -> None:
    _requires_live_db()
    _upgrade_head()
    store = _store()
    suffix = uuid.uuid4().hex
    review_id = f"review-{suffix}"
    check_id = f"check-{suffix}"
    review = await store.upsert_object(
        OntologyObjectRecord(
            id=review_id,
            object_type="ReviewCase",
            properties={"id": review_id, "status": "open"},
        )
    )
    updated = await store.upsert_object(
        OntologyObjectRecord(
            id=review_id,
            object_type="ReviewCase",
            properties={"id": review_id, "status": "in_review"},
        ),
        expected_revision=review.revision,
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id=check_id,
            object_type="ReviewCheck",
            properties={"id": check_id, "status": "blocked"},
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id=review_id,
            to_id=check_id,
        )
    )

    graph = await store.traverse(root_ids=(review_id,), max_depth=1)
    selected = await store.query_objects(
        object_types=("ReviewCheck",), property_equals={"status": "blocked"}
    )

    assert updated.revision == 2
    assert {item.id for item in graph.objects} == {review_id, check_id}
    assert len(graph.links) == 1
    assert any(item.id == check_id for item in selected.objects)
