"""Real PostgreSQL role and immutability checks for Rule activation receipts."""

from __future__ import annotations

import os
import runpy
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_rule_activation_receipts import (
    PostgresRuleActivationReceiptReader,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
CORE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/"
    "20260922_core_rule_activation_receipts.py"
)
OPERATOR_MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/"
    "20260922_operator_rule_activation_receipts.py"
)


@pytest.fixture
def database() -> Iterator[str]:
    source = os.environ.get("FDAI_RULE_ACTIVATION_TEST_DSN")
    if not source:
        pytest.skip("FDAI_RULE_ACTIVATION_TEST_DSN is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Rule activation database test requires a loopback-only fixture")
    database_name = "fdai_rule_activation_" + uuid4().hex[:12]
    statements: list[str] = []
    for path in (CORE_MIGRATION, OPERATOR_MIGRATION):
        module = runpy.run_path(str(path))
        with patch("alembic.op.execute", side_effect=statements.append):
            module["upgrade"]()
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_core') THEN
                CREATE ROLE fdai_core NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        dsn = make_conninfo(source, dbname=database_name)
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    """CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY, value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
                    GRANT USAGE ON SCHEMA public TO fdai_core, fdai_operator;
                    GRANT SELECT, INSERT, UPDATE ON state_kv TO fdai_operator"""
                )
                for statement in statements:
                    connection.execute(statement)
            yield dsn
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def _role(dsn: str, role: str) -> str:
    return make_conninfo(dsn, options=f"-c role={role}")


async def test_operator_source_insert_captures_an_unforgeable_receipt(database: str) -> None:
    proposal_ref = "operator-proposal:workflow:" + "a" * 64
    record = {
        "operation": "rule.activation-request",
        "principal_id": "requester",
        "dispatch_status": "pending",
    }
    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        operator.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s)",
            (proposal_ref, Jsonb(record)),
        )

    reader = PostgresRuleActivationReceiptReader(
        PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    )
    assert await reader.read_state(proposal_ref) == record

    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute(
                "INSERT INTO operator_rule_activation_receipt (proposal_ref, record) "
                "VALUES (%s, %s)",
                ("operator-proposal:workflow:" + "b" * 64, Jsonb(record)),
            )
    for statement in (
        "SELECT record FROM operator_rule_activation_receipt WHERE proposal_ref = %s",
        "UPDATE operator_rule_activation_receipt SET record = record WHERE proposal_ref = %s",
        "DELETE FROM operator_rule_activation_receipt WHERE proposal_ref = %s",
    ):
        with psycopg.connect(_role(database, "fdai_operator")) as operator:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                operator.execute(statement, (proposal_ref,))

    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        with pytest.raises(psycopg.errors.RaiseException, match="source request is immutable"):
            operator.execute(
                "UPDATE state_kv SET value = jsonb_set(value, '{principal_id}', %s) WHERE key = %s",
                (Jsonb("another-requester"), proposal_ref),
            )

    with psycopg.connect(_role(database, "fdai_operator")) as operator:
        operator.execute(
            "UPDATE state_kv SET value = jsonb_set(value, '{dispatch_status}', %s) WHERE key = %s",
            (Jsonb("published"), proposal_ref),
        )
    assert await reader.read_state(proposal_ref) == record
