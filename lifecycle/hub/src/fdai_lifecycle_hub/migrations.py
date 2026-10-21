"""Explicit, transactional Hub schema revisions. Serving never migrates a remote database."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

from sqlalchemy import Column, Engine, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection

REVISION = 1


def _revision(namespace: str) -> int:
    return 3 if namespace == "lifecycle_hub" else REVISION


def migrate(engine: Engine, namespace: str, initialize: Callable[[Connection], None]) -> None:
    from fdai_lifecycle_hub import configuration_import_models, models

    versions = _versions(namespace)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": namespace}
            )
        versions.create(connection, checkfirst=True)
        revision = connection.scalar(select(versions.c.revision))
        if revision is None:
            initialize(connection)
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
        elif revision is not None and revision != _revision(namespace):
            raise ValueError("Unsupported Hub schema revision; use a compatible migration command.")


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
