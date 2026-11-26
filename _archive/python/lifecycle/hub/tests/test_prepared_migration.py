from __future__ import annotations

import sys
from datetime import timedelta

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from lifecycle.hub.tests.test_remote_catalog import approve, source_for, vendor_for
from lifecycle.hub.tests.test_standalone_remote import engine as engine
from sqlalchemy import Column, Integer, MetaData, Table, event, func, inspect, select, text
from starlette.testclient import TestClient

from fdai_lifecycle_hub import configuration_import_models, local_channels, models, remote
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.cli import DATABASE_URL_ENV, main
from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.errors import SchemaMigrationPendingError
from fdai_lifecycle_hub.migrations import _versions, migrate, require_schema
from fdai_lifecycle_hub.remote_catalog import (
    CatalogSource,
    PinApproval,
    RemoteCatalog,
    bind_catalog,
    initialize_trust,
)
from fdai_lifecycle_hub.schemas import reported_state_json
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def hub_store(engine):
    store = HubStore(engine)
    store.create_schema()
    return store


def legacy_schema(engine, revision: int) -> None:
    with engine.begin() as connection:
        if revision < 3:
            added = {
                model.__tablename__
                for model in (
                    configuration_import_models.ConfigurationScopeRequest,
                    configuration_import_models.ConfigurationScopeApproval,
                    configuration_import_models.ConfigurationImport,
                    configuration_import_models.ConfigurationHead,
                    configuration_import_models.ConfigurationChangeApproval,
                    configuration_import_models.ConfigurationPlanImport,
                )
            }
            if revision == 1:
                added.update(
                    {
                        "lifecycle_configuration_key_request",
                        "lifecycle_configuration_key_binding",
                        "lifecycle_configuration_plan_trust",
                    }
                )
            for table in reversed(models.Base.metadata.sorted_tables):
                if table.name in added:
                    table.drop(connection, checkfirst=True)
        if revision < 4:
            local_channels.metadata.drop_all(connection)
        else:
            local_channels.metadata.create_all(connection)
        if revision < 5:
            if engine.dialect.name == "sqlite":
                metadata = MetaData()
                metadata.reflect(bind=connection)
                original = metadata.tables["lifecycle_entity_reported_state"]
                original.c.release_id.nullable = False
                replacement = original.to_metadata(metadata, name="legacy_entity_state")
                replacement.create(connection)
                connection.execute(
                    replacement.insert().from_select(list(original.c.keys()), select(*original.c))
                )
                connection.exec_driver_sql("DROP TABLE lifecycle_entity_reported_state")
                connection.exec_driver_sql(
                    "ALTER TABLE legacy_entity_state RENAME TO lifecycle_entity_reported_state"
                )
            else:
                connection.exec_driver_sql(
                    "ALTER TABLE lifecycle_entity_reported_state "
                    "ALTER COLUMN release_id SET NOT NULL"
                )
            connection.exec_driver_sql(
                "ALTER TABLE lifecycle_state_report DROP COLUMN available_artifact_digests"
            )
        versions = Table(
            "lifecycle_hub_schema_revision",
            MetaData(),
            Column("revision", Integer, primary_key=True),
        )
        versions.create(connection)
        connection.execute(versions.insert().values(revision=revision))


def no_initialization(connection):
    pytest.fail("Preparation must not initialize an absent database.")


def audit_count(engine):
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(models.AuditRecord))


@pytest.mark.parametrize("revision", [1, 2, 3, 4, 5])
def test_prepare_retains_legacy_reader_and_rows_until_explicit_completion(
    hub_store, installation, enroll, revision
):
    enroll(hub_store, installation)
    before = hub_store.load(installation.installation_id)
    legacy_schema(hub_store.engine, revision)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    with hub_store.engine.connect() as connection:
        assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == revision
    require_schema(hub_store.engine, "lifecycle_hub", allow_pre_native=True)
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        require_schema(hub_store.engine, "lifecycle_hub")
    assert hub_store.load(installation.installation_id) == before
    assert local_channels.entries.name in inspect(hub_store.engine).get_table_names()
    assert "available_artifact_digests" in {
        column["name"] for column in inspect(hub_store.engine).get_columns("lifecycle_state_report")
    }
    migrate(hub_store.engine, "lifecycle_hub", no_initialization)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization)
    require_schema(hub_store.engine, "lifecycle_hub")
    assert hub_store.load(installation.installation_id) == before


@pytest.mark.parametrize("phase", ["layout", "record"])
def test_preparation_interruption_rolls_back_layout_and_reader_floor(
    hub_store, installation, enroll, phase
):
    enroll(hub_store, installation)
    legacy_schema(hub_store.engine, 1)
    before_tables = set(inspect(hub_store.engine).get_table_names())

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if (
            phase == "layout"
            and statement.startswith("ALTER TABLE lifecycle_state_report ADD COLUMN")
        ) or (
            phase == "record"
            and statement.startswith("UPDATE lifecycle_hub_schema_revision")
            and "prepared_revision" in statement
        ):
            raise RuntimeError("injected_preparation_interruption")

    event.listen(hub_store.engine, "before_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="injected_preparation_interruption"):
            migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    finally:
        event.remove(hub_store.engine, "before_cursor_execute", interrupt)
    assert set(inspect(hub_store.engine).get_table_names()) == before_tables
    with hub_store.engine.connect() as connection:
        assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == 1
    assert "prepared_revision" not in {
        column["name"]
        for column in inspect(hub_store.engine).get_columns("lifecycle_hub_schema_revision")
    }


def test_unprepared_legacy_database_is_not_a_compatible_server(hub_store):
    legacy_schema(hub_store.engine, 1)
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        require_schema(hub_store.engine, "lifecycle_hub", allow_pre_native=True)


def test_preparation_never_initializes_a_database_or_changes_release_hub(engine):
    before = inspect(engine).get_table_names()
    with pytest.raises(ValueError, match="requires an existing"):
        migrate(engine, "lifecycle_hub", no_initialization, prepare=True)
    assert inspect(engine).get_table_names() == before
    migrate(engine, "release_hub", lambda _: None)
    with pytest.raises(ValueError, match="only for an existing Lifecycle Hub"):
        migrate(engine, "release_hub", no_initialization, prepare=True)
    require_schema(engine, "release_hub")
    assert [
        column["name"] for column in inspect(engine).get_columns("release_hub_schema_revision")
    ] == ["revision"]


def test_prepared_writers_fail_before_effects_and_resume_after_completion(
    hub_store, installation, enroll, key, now, caplog
):
    enroll(hub_store, installation)
    source = CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        token_scope="api://release/.default",
        managed_identity_client_id="synthetic-client",
        release_public_key=key.public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    )
    with hub_store.engine.begin() as connection:
        initialize_trust(connection, source)

    def no_fetch(source):
        pytest.fail("A prepared server must not download a replacement catalog.")

    catalog = RemoteCatalog(hub_store.engine, source, fetch=no_fetch)
    status = catalog.status()
    before = hub_store.load(installation.installation_id)
    before_audit = audit_count(hub_store.engine)
    legacy_schema(hub_store.engine, 1)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    installation_id = installation.installation_id
    for write in (
        lambda: hub_store.record_state(installation_id, before.reported, now=now),
        lambda: ConfigurationKeyStore(hub_store.engine).deny(
            installation_id, actor="operator", now=now, reason="synthetic_denial"
        ),
        lambda: ConfigurationImportStore(hub_store.engine).deny(
            installation_id, actor="operator", now=now, reason="synthetic_denial"
        ),
        lambda: bind_catalog(
            hub_store.engine, source, actor="operator", reason="Synthetic binding"
        ),
        lambda: catalog.approve(
            PinApproval(
                revision=1,
                sha256="a" * 64,
                reason="Synthetic approval",
                confirmation="approve 1 " + "a" * 64,
            ),
            actor="operator",
            now=now,
        ),
        lambda: catalog.import_once(actor="operator", now=now),
        lambda: catalog.recompute(hub_store, installation_id, key, now=now),
    ):
        with pytest.raises(SchemaMigrationPendingError):
            write()
    assert "hub_write_rejected reason=schema_migration_pending" in caplog.text
    assert catalog.status() == status
    assert hub_store.load(installation_id) == before
    with TestClient(create_app(hub_store, clock=lambda: now)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/installations").status_code == 200
        assert client.get(f"/v1/installations/{installation_id}/plan").status_code == 204
        response = client.post(
            f"/v1/installations/{installation_id}/state",
            content=reported_state_json.dump_json(before.reported),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 503
        assert response.json() == {"error": "schema_migration_pending"}
    assert audit_count(hub_store.engine) == before_audit
    migrate(hub_store.engine, "lifecycle_hub", no_initialization)
    assert hub_store.current_plan(installation_id, now=now) is None
    window = SuppressionWindow("installation", now, now + timedelta(minutes=5))
    hub_store.add_suppression(installation_id, window, now=now)
    assert hub_store.load(installation_id).suppressions == (window,)
    assert audit_count(hub_store.engine) == before_audit + 1


def test_remote_prepare_supports_actual_legacy_layout_before_serving(
    monkeypatch, tmp_path, hub_store, key
):
    legacy_schema(hub_store.engine, 1)
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG",
        '{"kind":"target","origin":"https://hub.example.com"}',
    )
    monkeypatch.setattr(remote, "remote_engine", lambda _: hub_store.engine)
    monkeypatch.setattr(remote, "remote_key", lambda _: key)
    monkeypatch.setattr(sys, "argv", ["remote", "prepare"])
    remote._run()
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    monkeypatch.setattr(sys, "argv", ["remote", "serve", "--ui", str(tmp_path)])
    remote._run()
    with TestClient(captured.pop(), base_url="https://hub.example.com") as client:
        assert client.get("/readyz").status_code == 200
        with hub_store.engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT revision FROM lifecycle_hub_schema_revision")) == 1
            )
        monkeypatch.setattr(sys, "argv", ["remote", "schema"])
        with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
            remote._run()
        monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
        remote._run()
        assert client.get("/readyz").status_code == 200
        require_schema(hub_store.engine, "lifecycle_hub")


def test_trusted_host_prepare_is_explicit_and_does_not_advance_reader_floor(
    tmp_path, monkeypatch, capsys
):
    engine = HubStore.connect(f"sqlite:///{tmp_path / 'legacy.db'}").engine
    HubStore(engine).create_schema()
    legacy_schema(engine, 1)
    monkeypatch.setenv(DATABASE_URL_ENV, str(engine.url))
    assert main(["prepare"]) == 0
    assert capsys.readouterr().out.strip() == '{"schema": "prepared"}'
    with engine.connect() as connection:
        assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == 1
    assert main(["migrate"]) == 0
    require_schema(engine, "lifecycle_hub")
    engine.dispose()


@pytest.mark.parametrize(("revision", "prepared"), [(1, 7), (6, 6), (7, 6)])
def test_invalid_transition_metadata_refuses_readiness_writes_and_migration(
    hub_store, revision, prepared
):
    legacy_schema(hub_store.engine, 1)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    with hub_store.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE lifecycle_hub_schema_revision "
                "SET revision=:revision, prepared_revision=:prepared"
            ),
            {"revision": revision, "prepared": prepared},
        )
    with pytest.raises(ValueError):
        require_schema(hub_store.engine, "lifecycle_hub", allow_pre_native=True)
    with pytest.raises(ValueError):
        with hub_store._write():
            pytest.fail("Invalid transition metadata must not admit writes.")
    with pytest.raises(ValueError):
        migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    with hub_store.engine.connect() as connection:
        assert connection.execute(
            text("SELECT revision, prepared_revision FROM lifecycle_hub_schema_revision")
        ).one() == (revision, prepared)


def test_prepared_catalog_preserves_read_only_inventory_and_local_channel_projection(
    hub_store, tmp_path, key, catalog, now
):
    raw = vendor_for(tmp_path, key, catalog, now).export()[0]
    source = source_for(key)
    with hub_store.engine.begin() as connection:
        initialize_trust(connection, source)
        local_channels.metadata.create_all(connection)
    target = RemoteCatalog(hub_store.engine, source, fetch=lambda _: raw)
    approve(target, raw, now)
    target.import_once(actor="operator", now=now)
    before = target.catalog(now)
    before_channels = target.local_channels(now=now)
    legacy_schema(hub_store.engine, 1)
    migrate(hub_store.engine, "lifecycle_hub", no_initialization, prepare=True)
    assert target.catalog(now) == before
    assert target.local_channels(now=now) == before_channels
