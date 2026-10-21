from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import parse_lifecycle_release_manifest
from lifecycle.hub.tests.test_application_release import manifest
from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.engine import Connection

from fdai_lifecycle_hub import cli, domain, models, schemas
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.domain import Configuration, EntityState, Health, Issued, NoEligibleRelease
from fdai_lifecycle_hub.entity import EntitySettings
from fdai_lifecycle_hub.errors import EntitySettingsRejectedError
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest, settings_digest
from fdai_lifecycle_hub.migrations import _versions, migrate, require_schema
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.store import HubStore

IMAGE = "sha256:" + "b" * 64
OVERRIDES = ({"versions": ">=0.0.0", "values": {}},)


def first_install(installation):
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    return replace(
        installation,
        settings=replace(
            installation.settings, product="example-web", channel="DEV", version_range=">=0.0.0"
        ),
        entities=frozenset({replace(core, settings=EntitySettings(overrides=OVERRIDES))}),
        configuration=Configuration(schema={}, environment={}, entity_overrides=OVERRIDES),
        reported=replace(
            installation.reported,
            schema_revision=0,
            entities={
                "core": EntityState(
                    release_id=None, artifact_digests=frozenset(), health=Health.UNKNOWN
                )
            },
            available_artifact_digests=frozenset({IMAGE}),
        ),
    )


def first_catalog():
    release = parse_lifecycle_release_manifest(
        canonical_bytes(manifest() | {"release_version": "0.0.0"})
    )
    return ReleaseCatalog(releases={"0.0.0": release}, channels={"DEV": frozenset({"0.0.0"})})


def test_real_zero_version_is_an_eligible_first_release(installation, key, now):
    fresh = first_install(installation)
    assert fresh.current_release is None
    outcome = plan_next(fresh, now, catalog=first_catalog(), key=key)
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "0.0.0"
    assert outcome.plan.source_state_digest == fresh.reported.digest
    assert outcome.plan.envelope.destructive_allowed is False
    key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)


def test_explicit_empty_staging_inventory_does_not_fall_back_to_running_images(
    installation, key, now
):
    fresh = first_install(installation)
    unavailable = replace(
        fresh, reported=replace(fresh.reported, available_artifact_digests=frozenset())
    )
    outcome = plan_next(unavailable, now, catalog=first_catalog(), key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert outcome.checks
    assert any("artifact" in block.reason_code for block in outcome.checks[0].blocks)
    legacy = replace(installation.reported, available_artifact_digests=None)
    assert legacy.artifact_digests() == installation.reported.artifact_digests()
    assert replace(legacy, available_artifact_digests=frozenset()).artifact_digests() == frozenset()


@pytest.mark.parametrize(
    "health,images", [(Health.HEALTHY, frozenset()), (Health.UNKNOWN, frozenset({IMAGE}))]
)
def test_absence_cannot_claim_a_successful_or_running_release(health, images):
    with pytest.raises(ValueError, match="uninstalled entity"):
        EntityState(release_id=None, artifact_digests=images, health=health)


@pytest.mark.parametrize("inventory", [frozenset({"latest"}), frozenset({"sha256:short"})])
def test_staging_inventory_validates_immutable_digests(installation, inventory):
    with pytest.raises(ValueError, match="available artifact"):
        replace(installation.reported, available_artifact_digests=inventory)


def test_an_uninstalled_managed_entity_keeps_a_partial_installation_in_first_install(
    installation, key, now
):
    fresh = first_install(installation)
    installed = next(iter(fresh.entities))
    mixed = replace(
        fresh,
        entities=fresh.entities | {replace(installed, entity_id="other")},
        reported=replace(
            fresh.reported,
            entities=fresh.reported.entities | {"other": installation.reported.entities["core"]},
        ),
    )
    assert mixed.current_release is None
    outcome = plan_next(mixed, now, catalog=first_catalog(), key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert outcome.checks[0].blocks[0].reason_code == "release_would_downgrade_entity"
    catalog = ReleaseCatalog(
        releases={
            "1.4.0": parse_lifecycle_release_manifest(
                canonical_bytes(manifest() | {"release_version": "1.4.0"})
            )
        },
        channels={"DEV": frozenset({"1.4.0"})},
    )
    same_version = plan_next(mixed, now, catalog=catalog, key=key)
    assert isinstance(same_version, Issued)
    assert same_version.plan.target_release_id == "1.4.0"


def test_empty_state_round_trips_and_requires_explicit_initial_override_coverage(
    hub_store, installation, enroll, key, now, tmp_path, monkeypatch, capsys
):
    fresh = first_install(installation)
    unbound = replace(
        fresh,
        settings=replace(fresh.settings, product=None),
        entities=frozenset(replace(entity, settings=None) for entity in fresh.entities),
    )
    enroll(hub_store, unbound)
    settings = next(iter(fresh.entities)).settings
    with pytest.raises(EntitySettingsRejectedError, match="initial_release_required"):
        hub_store.manage(fresh.installation_id, "core", settings, operator="operator", now=now)
    assert not hub_store.load(fresh.installation_id).managed_entity_ids
    path = tmp_path / "entity-settings.json"
    path.write_bytes(schemas.entity_settings_json.dump_json(settings))
    monkeypatch.setattr(cli, "_store", lambda: hub_store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    assert (
        cli.main(
            [
                "manage",
                fresh.installation_id,
                "core",
                str(path),
                "--operator",
                "operator",
                "--initial-release",
                "0.0.0",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["covering_range"] == ">=0.0.0"
    before = settings_digest(hub_store.load(fresh.installation_id).settings)
    hub_store.bind_application(
        fresh.installation_id,
        ApplicationBindingRequest(
            request_id=UUID(int=1),
            expected_settings_digest=before,
            product="example-web",
            reason_code="initial_application_binding",
            confirmation=f"bind application {fresh.installation_id} example-web {before}",
        ),
        operator="operator",
        now=now,
    )
    reopened = HubStore(hub_store.engine)
    loaded = reopened.load(fresh.installation_id)
    assert loaded.reported == fresh.reported
    outcome = reopened.recompute(
        fresh.installation_id,
        lambda current, at: plan_next(current, at, catalog=first_catalog(), key=key),
        now=now,
    )
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "0.0.0"


def test_existing_installation_cannot_bypass_running_override_coverage(
    hub_store, installation, enroll, now
):
    enroll(hub_store, installation)
    settings = next(entity.settings for entity in installation.entities if entity.settings)
    with pytest.raises(EntitySettingsRejectedError, match="requires_uninstalled_entity"):
        hub_store.manage(
            installation.installation_id,
            "core",
            settings,
            operator="operator",
            now=now,
            initial_release="0.0.0",
        )


def test_sqlite_revision_three_migration_retains_rows_constraints_and_digests(
    tmp_path, installation, enroll, now, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    store = HubStore(engine)
    store.create_schema()
    enroll(store, installation)
    original_state = store.load(installation.installation_id).reported
    with engine.begin() as connection:
        metadata = MetaData()
        metadata.reflect(bind=connection)
        original = metadata.tables["lifecycle_entity_reported_state"]
        original.c.release_id.nullable = False
        old = original.to_metadata(metadata, name="legacy_entity_state")
        old.create(connection)
        connection.execute(old.insert().from_select(list(original.c.keys()), select(*original.c)))
        connection.exec_driver_sql("DROP TABLE lifecycle_entity_reported_state")
        connection.exec_driver_sql(
            "ALTER TABLE legacy_entity_state RENAME TO lifecycle_entity_reported_state"
        )
        connection.exec_driver_sql(
            "ALTER TABLE lifecycle_state_report DROP COLUMN available_artifact_digests"
        )
        versions = _versions("lifecycle_hub")
        versions.create(connection)
        connection.execute(versions.insert().values(revision=3))
    with pytest.raises(ValueError, match="migrate before serving"):
        require_schema(engine, "lifecycle_hub")

    def initialize(connection):
        models.Base.metadata.create_all(connection)

    execute = Connection.exec_driver_sql

    def interrupted(connection, statement, *args, **kwargs):
        if statement.startswith(
            "ALTER TABLE lifecycle_state_report ADD COLUMN available_artifact_digests"
        ):
            raise RuntimeError("injected_migration_interruption")
        return execute(connection, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Connection, "exec_driver_sql", interrupted)
        with pytest.raises(RuntimeError, match="injected_migration_interruption"):
            migrate(engine, "lifecycle_hub", initialize)
    with engine.connect() as connection:
        assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == 3
        assert (
            connection.scalar(
                select(models.EntityReportedState.release_id).where(
                    models.EntityReportedState.entity_id == "core"
                )
            )
            == original_state.entities["core"].release_id
        )
    assert (
        next(
            column
            for column in inspect(engine).get_columns("lifecycle_entity_reported_state")
            if column["name"] == "release_id"
        )["nullable"]
        is False
    )
    migrate(engine, "lifecycle_hub", initialize)
    migrate(engine, "lifecycle_hub", initialize)
    require_schema(engine, "lifecycle_hub")
    assert store.load(installation.installation_id).reported == original_state
    schema = inspect(engine)
    assert schema.get_pk_constraint("lifecycle_entity_reported_state")["constrained_columns"] == [
        "report_id",
        "entity_id",
    ]
    assert len(schema.get_foreign_keys("lifecycle_entity_reported_state")) == 2
    fresh = replace(
        original_state,
        observed_at=now + timedelta(seconds=1),
        entities=original_state.entities
        | {
            "core": EntityState(
                release_id=None, artifact_digests=frozenset(), health=Health.UNKNOWN
            )
        },
        available_artifact_digests=frozenset({IMAGE}),
    )
    store.record_state(installation.installation_id, fresh, now=fresh.observed_at)
    assert HubStore(engine).load(installation.installation_id).reported == fresh
    engine.dispose()
