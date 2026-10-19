"""Real PostgreSQL checks for pending observations scoped to ontology reads."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.delivery.persistence.postgres_ontology_source_coverage import (
    OBSERVATION_PENDING,
    resource_graph_source_coverage_detail,
)

from tests.persistence.test_postgres_ontology_instance import _isolated_committed_resource_store

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("exact_subjects", "subject_types", "pending_ref", "pending_type", "complete"),
    [
        (("resource-00000",), (), "resource-00000", "virtual-machine", False),
        (("resource-00000",), (), "resource-other", "virtual-machine", True),
        ((), ("virtual-machine",), "resource-other", "virtual-machine", False),
        ((), ("virtual-machine",), "resource-other", "object-storage", True),
        (
            ("resource-00000",),
            ("virtual-machine",),
            "resource-00000",
            "virtual-machine",
            False,
        ),
        (
            ("resource-00000",),
            ("virtual-machine",),
            "resource-other",
            "virtual-machine",
            True,
        ),
        ((), (), "resource-other", "object-storage", False),
    ],
)
async def test_pending_observation_limits_only_the_selected_identity_or_type(
    exact_subjects, subject_types, pending_ref, pending_type, complete
):
    async with _isolated_committed_resource_store() as (store, _):
        async with await store._connect() as connection:
            await connection.execute(
                "INSERT INTO inventory_observation_journal "
                "(scope_ref,watermark,source_revision,effective_at,"
                "subject_kind,subject_ref,subject_type) "
                "SELECT 'scope-example',1,'next',started_at+INTERVAL '1 second',"
                "'object',%s,%s FROM inventory_snapshot",
                (pending_ref, pending_type),
            )
            coverage = await resource_graph_source_coverage_detail(
                connection,
                (),
                requires_resource_coverage=True,
                expresses_relationships=False,
                exact_subjects=exact_subjects,
                subject_types=subject_types,
            )

        assert coverage.complete is complete
        assert coverage.generation == "snapshot-example"
        assert coverage.reason == (None if complete else OBSERVATION_PENDING)


@pytest.mark.parametrize("expresses_relationships", [False, True])
async def test_unscoped_pending_observation_does_not_become_complete(expresses_relationships):
    async with _isolated_committed_resource_store() as (store, _):
        async with await store._connect() as connection:
            await connection.execute(
                "INSERT INTO inventory_observation_journal "
                "(scope_ref,watermark,source_revision,effective_at) "
                "SELECT 'scope-example',1,'next',started_at+INTERVAL '1 second' "
                "FROM inventory_snapshot"
            )
            coverage = await resource_graph_source_coverage_detail(
                connection,
                (),
                requires_resource_coverage=True,
                expresses_relationships=expresses_relationships,
            )

        assert coverage.complete is False
        assert coverage.reason == OBSERVATION_PENDING


@pytest.mark.parametrize(
    ("scope", "source_revision", "time_offset", "complete"),
    [
        ("scope-example", "next", timedelta(seconds=1), False),
        ("scope-other", "next", timedelta(seconds=1), True),
        ("scope-example", "snapshot-example", timedelta(seconds=1), True),
        ("scope-example", "next", timedelta(0), True),
        ("scope-example", "next", timedelta(seconds=-1), True),
    ],
)
async def test_pending_observation_keeps_scope_generation_and_cutoff(
    scope, source_revision, time_offset, complete
):
    async with _isolated_committed_resource_store() as (store, _):
        async with await store._connect() as connection:
            await connection.execute(
                "INSERT INTO inventory_observation_journal "
                "(scope_ref,watermark,source_revision,effective_at,"
                "subject_kind,subject_ref,subject_type) "
                "SELECT %s,1,%s,started_at+%s,'object','resource-00000','virtual-machine' "
                "FROM inventory_snapshot",
                (scope, source_revision, time_offset),
            )
            coverage = await resource_graph_source_coverage_detail(
                connection,
                (),
                requires_resource_coverage=True,
                expresses_relationships=False,
                subject_types=("virtual-machine",),
            )

        assert coverage.complete is complete
        assert coverage.generation == "snapshot-example"
        assert coverage.reason == (None if complete else OBSERVATION_PENDING)
