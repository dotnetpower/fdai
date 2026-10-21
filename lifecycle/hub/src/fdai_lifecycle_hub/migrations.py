"""Explicit, transactional Hub schema revisions. Serving never migrates a remote database."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

from sqlalchemy import Column, Engine, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection

REVISION = 1


def _revision(namespace: str) -> int:
    return 6 if namespace == "lifecycle_hub" else REVISION


def migrate(engine: Engine, namespace: str, initialize: Callable[[Connection], None]) -> None:
    from fdai_lifecycle_hub import configuration_import_models, local_channels, models

    versions = _versions(namespace)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": namespace}
            )
        elif engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        versions.create(connection, checkfirst=True)
        revision = connection.scalar(select(versions.c.revision))
        if revision is None:
            initialize(connection)
            if namespace == "lifecycle_hub":
                local_channels.metadata.create_all(connection)
            connection.execute(versions.insert().values(revision=_revision(namespace)))
        elif revision == 1 and namespace == "lifecycle_hub":
            models.Base.metadata.tables["lifecycle_configuration_key_request"].create(
                connection, checkfirst=True
            )
            models.Base.metadata.tables["lifecycle_configuration_key_binding"].create(
                connection, checkfirst=True
            )
            models.Base.metadata.tables["lifecycle_configuration_plan_trust"].create(
                connection, checkfirst=True
            )
            revision = 2
        if revision == 2 and namespace == "lifecycle_hub":
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
        if revision == 3 and namespace == "lifecycle_hub":
            local_channels.metadata.create_all(connection)
            connection.execute(versions.update().values(revision=4))
            revision = 4
        if revision == 4 and namespace == "lifecycle_hub":
            _empty_state_migration(connection)
            connection.execute(versions.update().values(revision=5))
            revision = 5
        if revision == 5 and namespace == "lifecycle_hub":
            # Old readers cannot interpret native ownership metadata.
            connection.execute(versions.update().values(revision=6))
            revision = 6
        if revision is not None and revision != _revision(namespace):
            raise ValueError("Unsupported Hub schema revision; use a compatible migration command.")


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


def require_schema(engine: Engine | Connection, namespace: str) -> None:
    versions = _versions(namespace)
    with engine.connect() if isinstance(engine, Engine) else nullcontext(engine) as connection:
        if not inspect(connection).has_table(versions.name):
            raise ValueError("Hub schema is not migrated; run the explicit migrate command.")
        if connection.scalar(select(versions.c.revision)) != _revision(namespace):
            raise ValueError("Unsupported Hub schema revision; migrate before serving.")


def _versions(namespace: str) -> Table:
    if namespace not in {"release_hub", "lifecycle_hub"}:
        raise ValueError("Unknown Hub migration namespace.")
    return Table(
        f"{namespace}_schema_revision", MetaData(), Column("revision", Integer, primary_key=True)
    )
