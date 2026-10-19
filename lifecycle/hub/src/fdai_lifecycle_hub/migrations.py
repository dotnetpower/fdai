"""Explicit, transactional Hub schema revisions. Serving never migrates a remote database."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

from sqlalchemy import Column, Engine, Integer, MetaData, Table, inspect, select, text
from sqlalchemy.engine import Connection

REVISION = 1


def migrate(engine: Engine, namespace: str, initialize: Callable[[Connection], None]) -> None:
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
            connection.execute(versions.insert().values(revision=REVISION))
        elif revision != REVISION:
            raise ValueError("Unsupported Hub schema revision; use a compatible migration command.")


def require_schema(engine: Engine | Connection, namespace: str) -> None:
    versions = _versions(namespace)
    with engine.connect() if isinstance(engine, Engine) else nullcontext(engine) as connection:
        if not inspect(connection).has_table(versions.name):
            raise ValueError("Hub schema is not migrated; run the explicit migrate command.")
        if connection.scalar(select(versions.c.revision)) != REVISION:
            raise ValueError("Unsupported Hub schema revision; migrate before serving.")


def _versions(namespace: str) -> Table:
    if namespace not in {"release_hub", "lifecycle_hub"}:
        raise ValueError("Unknown Hub migration namespace.")
    return Table(
        f"{namespace}_schema_revision", MetaData(), Column("revision", Integer, primary_key=True)
    )
