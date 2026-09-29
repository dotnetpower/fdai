"""Loopback PostgreSQL checks for Operator authentication receipt retention.

Set FDAI_OPERATIONAL_EVIDENCE_TEST_DSN to a loopback PostgreSQL admin DSN.
"""

from __future__ import annotations

import os
import runpy
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
CORE_MIGRATION = ROOT / (
    "service-migrations/branches/core-control-plane/versions/20260928_core_operational_evidence.py"
)
MIGRATION = ROOT / (
    "service-migrations/branches/operator-service/versions/"
    "20260929_operator_authentication_receipts.py"
)


@pytest.fixture
def database() -> Iterator[tuple[str, list[str]]]:
    source = os.environ.get("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN")
    if not source:
        pytest.skip("FDAI_OPERATIONAL_EVIDENCE_TEST_DSN is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parameters = conninfo_to_dict(source)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("authentication receipt database test requires a loopback-only fixture")
    name = "fdai_auth_receipt_" + uuid4().hex[:12]
    core_module = runpy.run_path(str(CORE_MIGRATION))
    module = runpy.run_path(str(MIGRATION))
    core_upgrade: list[str] = []
    upgrade: list[str] = []
    downgrade: list[str] = []
    with patch("alembic.op.execute", side_effect=core_upgrade.append):
        core_module["upgrade"]()
    with patch("alembic.op.execute", side_effect=upgrade.append):
        module["upgrade"]()
    with patch("alembic.op.execute", side_effect=downgrade.append):
        module["downgrade"]()
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        dsn = make_conninfo(source, dbname=name)
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute(
                    """CREATE TABLE state_kv (
                        key TEXT PRIMARY KEY, value JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
                    CREATE TABLE audit_log (
                        seq BIGSERIAL PRIMARY KEY, action_kind TEXT NOT NULL,
                        entry JSONB NOT NULL,
                        previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL UNIQUE);
                    GRANT USAGE ON SCHEMA public TO fdai_operator;"""
                )
                for statement in core_upgrade:
                    connection.execute(statement)
                assert _role_exists(connection, "fdai_operational_evidence_verifier")
                for statement in upgrade:
                    connection.execute(statement)
            yield dsn, downgrade
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _role(dsn: str, role: str) -> str:
    return make_conninfo(dsn, options=f"-c role={role}")


def _role_exists(connection: psycopg.Connection[object], role: str) -> bool:
    row = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    return row is not None


def test_receipt_store_is_insert_only_and_exact_function_detects_rows(
    database: tuple[str, list[str]],
) -> None:
    dsn, _downgrade = database
    digest = "sha256:" + "a" * 64
    receipt = {
        "schema_version": "1.0.0",
        "receipt_digest": digest,
        "subject_id": "operator-one",
        "groups": ["group-one"],
    }
    with psycopg.connect(_role(dsn, "fdai_operator")) as operator:
        operator.execute(
            "INSERT INTO operator_authentication_receipt "
            "(receipt_digest, request_id, principal_id, receipt) VALUES (%s, %s, %s, %s)",
            (digest, "semantic-request-one", "operator-one", Jsonb(receipt)),
        )
        operator.commit()
        for statement in (
            "UPDATE operator_authentication_receipt SET receipt = receipt "
            "WHERE receipt_digest = %s",
            "DELETE FROM operator_authentication_receipt WHERE receipt_digest = %s",
        ):
            with pytest.raises(
                (psycopg.errors.RaiseException, psycopg.errors.InsufficientPrivilege)
            ):
                operator.execute(statement, (digest,))
            operator.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            operator.execute("SELECT receipt FROM operator_authentication_receipt")

    with psycopg.connect(_role(dsn, "fdai_operational_evidence_verifier")) as verifier:
        rows = verifier.execute(
            "SELECT request_id, principal_id, receipt "
            "FROM fdai_operator_authentication_receipts_for_digest(%s)",
            (digest,),
        ).fetchall()
        assert rows == [("semantic-request-one", "operator-one", receipt)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            verifier.execute("SELECT receipt FROM operator_authentication_receipt")


def test_receipt_migration_downgrade_is_symmetric_after_drain(
    database: tuple[str, list[str]],
) -> None:
    dsn, downgrade = database
    with psycopg.connect(_role(dsn, "fdai_operator")) as operator:
        operator.execute(
            "INSERT INTO operator_authentication_receipt "
            "(receipt_digest, request_id, principal_id, receipt) VALUES (%s, %s, %s, %s)",
            ("sha256:" + "b" * 64, "request-two", "operator-two", Jsonb({"ok": True})),
        )
        operator.commit()
    with psycopg.connect(dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(downgrade[0])
        connection.rollback()
        connection.execute(
            "ALTER TABLE operator_authentication_receipt "
            "DISABLE TRIGGER operator_auth_receipt_delete_immutable"
        )
        connection.execute("DELETE FROM operator_authentication_receipt")
        connection.execute(
            "ALTER TABLE operator_authentication_receipt "
            "ENABLE TRIGGER operator_auth_receipt_delete_immutable"
        )
        for statement in downgrade:
            connection.execute(statement)
        with pytest.raises(psycopg.errors.UndefinedTable):
            connection.execute("SELECT count(*) FROM operator_authentication_receipt")
