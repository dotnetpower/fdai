from __future__ import annotations

from datetime import timedelta

import pytest
from lifecycle.hub.tests.test_prepared_migration import legacy_schema, no_initialization
from lifecycle.hub.tests.test_remote_catalog import source_for
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError

from fdai_lifecycle_hub import (
    configuration_import_store,
    configuration_key_store,
    models,
    remote_catalog,
    store,
)
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.errors import SchemaMigrationPendingError
from fdai_lifecycle_hub.migrations import _versions, migrate


@pytest.mark.parametrize("surface", ["store", "keys", "imports", "catalog"])
def test_sqlite_preparation_cannot_commit_between_writer_admission_and_effect(
    tmp_path, installation, enroll, now, key, monkeypatch, surface
):
    hub = store.HubStore.connect(f"sqlite:///{tmp_path / 'interleave.db'}")
    other = create_engine(hub.engine.url, connect_args={"timeout": 0.02})
    try:
        hub.create_schema()
        enroll(hub, installation)
        source = source_for(key)
        with hub.engine.begin() as connection:
            remote_catalog.initialize_trust(connection, source)
        legacy_schema(hub.engine, 1)
        target = remote_catalog.RemoteCatalog(hub.engine, source)
        module = {
            "store": store,
            "keys": configuration_key_store,
            "imports": configuration_import_store,
            "catalog": remote_catalog,
        }[surface]
        original = module.require_writable_schema
        admitted = []

        def interleave(connection):
            original(connection)
            with pytest.raises(OperationalError, match="database is locked"):
                migrate(other, "lifecycle_hub", no_initialization, prepare=True)
            admitted.append(True)

        monkeypatch.setattr(module, "require_writable_schema", interleave)

        def write():
            if surface == "store":
                with hub._write() as session:
                    session.execute(
                        models.Installation.__table__.update().values(
                            recorded_at=now + timedelta(seconds=1)
                        )
                    )
            elif surface in {"keys", "imports"}:
                decisions = (
                    configuration_key_store.ConfigurationKeyStore(hub.engine)
                    if surface == "keys"
                    else configuration_import_store.ConfigurationImportStore(hub.engine)
                )
                decisions.deny(
                    installation.installation_id,
                    actor="operator",
                    now=now,
                    reason="synthetic_denial",
                )
            else:
                target.approve(
                    remote_catalog.PinApproval(
                        revision=1,
                        sha256="a" * 64,
                        reason="Synthetic approval",
                        confirmation="approve 1 " + "a" * 64,
                    ),
                    actor="operator",
                    now=now,
                )

        if surface in {"keys", "imports"}:
            with pytest.raises(KeyBindingError, match="synthetic_denial"):
                write()
        else:
            write()
        assert admitted == [True]
        with other.connect() as connection:
            assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == 1
        migrate(other, "lifecycle_hub", no_initialization, prepare=True)
        with pytest.raises(SchemaMigrationPendingError):
            write()
        assert admitted == [True]
    finally:
        other.dispose()
        hub.engine.dispose()


def test_sqlite_borrowed_transaction_remains_owned_by_the_caller(tmp_path):
    hub = store.HubStore.connect(f"sqlite:///{tmp_path / 'borrowed.db'}")
    try:
        with hub.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE transaction_probe (value INTEGER)")
        with hub.engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            with hub.with_connection(connection)._write() as session:
                session.execute(text("INSERT INTO transaction_probe VALUES (1)"))
            assert connection.scalar(text("SELECT count(*) FROM transaction_probe")) == 1
            transaction.rollback()
        with hub.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM transaction_probe")) == 0
    finally:
        hub.engine.dispose()
