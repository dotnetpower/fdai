"""Explicit, transactional Hub schema revisions. Serving never migrates a remote database."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import nullcontext

from sqlalchemy import Column, Engine, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection

from fdai_lifecycle_hub.errors import SchemaMigrationPendingError

REVISION = 1
logger = logging.getLogger(__name__)


def _revision(namespace: str) -> int:
    return 6 if namespace == "lifecycle_hub" else REVISION


def migrate(
    engine: Engine,
    namespace: str,
    initialize: Callable[[Connection], None],
    *,
    prepare: bool = False,
) -> None:
    """Expand an existing schema without moving its reader floor, or explicitly finish migration."""
    from fdai_lifecycle_hub import local_channels

    versions = _versions(namespace)
    if prepare and namespace != "lifecycle_hub":
        raise ValueError("Preparation is supported only for an existing Lifecycle Hub.")
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": namespace}
            )
        elif engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        if prepare and not inspect(connection).has_table(versions.name):
            raise ValueError("Preparation requires an existing migrated Lifecycle Hub.")
        versions.create(connection, checkfirst=True)
        revision = connection.scalars(select(versions.c.revision)).one_or_none()
        if revision is None:
            if prepare:
                raise ValueError("Preparation requires an existing migrated Lifecycle Hub.")
            initialize(connection)
            if namespace == "lifecycle_hub":
                local_channels.metadata.create_all(connection)
            connection.execute(versions.insert().values(revision=_revision(namespace)))
            return
        if revision not in range(1, _revision(namespace) + 1):
            raise ValueError("Unsupported Hub schema revision; use a compatible migration command.")
        prepared = _prepared_revision(connection, versions)
        if prepared is not None:
            if revision == _revision(namespace):
                raise ValueError("Prepared Hub schema requires a pre-native reader floor.")
            if not prepare:
                connection.execute(versions.update().values(revision=6, prepared_revision=None))
            return
        if revision == _revision(namespace):
            return
        _upgrade_legacy(connection, versions, revision)
        if prepare:
            if "prepared_revision" not in versions.c:
                connection.exec_driver_sql(
                    "ALTER TABLE lifecycle_hub_schema_revision ADD COLUMN prepared_revision INTEGER"
                )
                versions.append_column(Column("prepared_revision", Integer))
            connection.execute(versions.update().values(revision=revision, prepared_revision=6))


def _upgrade_legacy(connection: Connection, versions: Table, revision: int) -> None:
    from fdai_lifecycle_hub import configuration_import_models, local_channels, models

    if revision == 1:
        for name in (
            "lifecycle_configuration_key_request",
            "lifecycle_configuration_key_binding",
            "lifecycle_configuration_plan_trust",
        ):
            models.Base.metadata.tables[name].create(connection, checkfirst=True)
        revision = 2
    if revision == 2:
        for model in (
            configuration_import_models.ConfigurationScopeRequest,
            configuration_import_models.ConfigurationScopeApproval,
            configuration_import_models.ConfigurationImport,
            configuration_import_models.ConfigurationHead,
            configuration_import_models.ConfigurationChangeApproval,
            configuration_import_models.ConfigurationPlanImport,
        ):
            models.Base.metadata.tables[model.__tablename__].create(connection, checkfirst=True)
        connection.execute(versions.update().values(revision=3))
        revision = 3
    if revision == 3:
        local_channels.metadata.create_all(connection)
        connection.execute(versions.update().values(revision=4))
        revision = 4
    if revision == 4:
        _empty_state_migration(connection)
    connection.execute(versions.update().values(revision=6))


def _prepared_revision(connection: Connection, versions: Table) -> int | None:
    if versions.name != "lifecycle_hub_schema_revision" or not any(
        column["name"] == "prepared_revision"
        for column in inspect(connection).get_columns(versions.name)
    ):
        return None
    versions.append_column(Column("prepared_revision", Integer))
    prepared: int | None = connection.scalar(select(versions.c.prepared_revision))
    if prepared not in (None, 6):
        raise ValueError(
            "Unsupported Hub preparation revision; use a compatible migration command."
        )
    return prepared


def require_writable_schema(connection: Connection) -> None:
    """Fence new writers during preparation without changing unversioned or legacy CLI behavior."""
    begin_sqlite_write(connection)
    versions = _versions("lifecycle_hub")
    if not inspect(connection).has_table(versions.name):
        return
    revision = connection.scalars(select(versions.c.revision)).one_or_none()
    prepared = _prepared_revision(connection, versions)
    if revision in (1, 2, 3, 4, 5, 6) and prepared is None:
        return
    if revision in (1, 2, 3, 4, 5) and prepared == 6:
        logger.warning("hub_write_rejected reason=schema_migration_pending")
        raise SchemaMigrationPendingError(
            "Hub schema migration is pending; complete explicit migrate before writes."
        )
    raise ValueError("Unsupported Hub schema revision; migrate before writing.")


def begin_sqlite_write(connection: Connection) -> None:
    """Hold SQLite writer admission through commit without resetting an inherited transaction."""
    if connection.dialect.name != "sqlite":
        return
    driver = connection.connection.driver_connection
    if not isinstance(driver, sqlite3.Connection):
        raise ValueError("Hub SQLite writes require the sqlite3 driver.")
    if not driver.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _empty_state_migration(connection: Connection) -> None:
    from fdai_lifecycle_hub import models

    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "ALTER TABLE lifecycle_entity_reported_state ALTER COLUMN release_id DROP NOT NULL"
        )
        inventory_type = "JSONB"
    elif connection.dialect.name == "sqlite":
        metadata = MetaData()
        for model in (models.Entity, models.StateReport):
            models.Base.metadata.tables[model.__tablename__].to_metadata(metadata)
        original = models.Base.metadata.tables[models.EntityReportedState.__tablename__]
        replacement = original.to_metadata(metadata, name="lifecycle_entity_reported_state_v5")
        replacement.create(connection)
        connection.execute(
            replacement.insert().from_select(list(original.c.keys()), select(*original.c))
        )
        connection.exec_driver_sql("DROP TABLE lifecycle_entity_reported_state")
        connection.exec_driver_sql(
            "ALTER TABLE lifecycle_entity_reported_state_v5 "
            "RENAME TO lifecycle_entity_reported_state"
        )
        inventory_type = "JSON"
    else:
        raise ValueError("Empty-state migration supports PostgreSQL and SQLite only.")
    connection.exec_driver_sql(
        "ALTER TABLE lifecycle_state_report ADD COLUMN available_artifact_digests " + inventory_type
    )


def require_schema(
    engine: Engine | Connection, namespace: str, *, allow_pre_native: bool = False
) -> None:
    versions = _versions(namespace)
    allowed = {_revision(namespace)}
    if namespace == "lifecycle_hub" and allow_pre_native:
        allowed.add(5)
    with engine.connect() if isinstance(engine, Engine) else nullcontext(engine) as connection:
        if not inspect(connection).has_table(versions.name):
            raise ValueError("Hub schema is not migrated; run the explicit migrate command.")
        revision = connection.scalars(select(versions.c.revision)).one_or_none()
        prepared = _prepared_revision(connection, versions)
        if namespace == "lifecycle_hub" and allow_pre_native and prepared == 6:
            allowed.update({1, 2, 3, 4})
        if revision not in allowed or (revision == 6 and prepared is not None):
            raise ValueError("Unsupported Hub schema revision; migrate before serving.")


def _versions(namespace: str) -> Table:
    if namespace not in {"release_hub", "lifecycle_hub"}:
        raise ValueError("Unknown Hub migration namespace.")
    return Table(
        f"{namespace}_schema_revision", MetaData(), Column("revision", Integer, primary_key=True)
    )
