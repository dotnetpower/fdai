import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai.core.licensing.entitlement import EntitlementSourceUnavailableError, LicenseStatus
from fdai.core.licensing.entitlement_source import EntitlementAcceptanceConflictError
from fdai.delivery.persistence.postgres_licensing_token import PostgresAcceptedEntitlementStore
from fdai_service_contracts.installation_entitlement_transport import entitlement_recipient
from psycopg import sql

from tests.core.licensing.test_accepted_entitlement_source import signed_authority
from tests.core.licensing.test_installation_entitlement import (
    _DEPLOYMENT,
    _INSTALLATION,
    _NOW,
    _claims,
    _token,
)
from tests.persistence.test_postgres_state_store import saga_database as saga_database

ROOT = Path(__file__).resolve().parents[4]
MIGRATION = (
    ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20261021_core_accepted_entitlement.py"
)
pytestmark = pytest.mark.integration


def migration_sql(*, downgrade: bool = False, path: Path = MIGRATION) -> str:
    spec = importlib.util.spec_from_file_location("accepted_entitlement_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    module.op = SimpleNamespace(execute=statements.append)
    (module.downgrade if downgrade else module.upgrade)()
    return "\n".join(statements)


@pytest.fixture
async def entitlement_database(saga_database: str) -> str:
    async with await psycopg.AsyncConnection.connect(saga_database) as connection:
        await _ensure_licensing_test_roles(connection)
        await connection.execute(migration_sql())
        await connection.execute(
            migration_sql(path=MIGRATION.with_name("20260929_core_licensing_trial.py"))
        )
    return saga_database


async def _ensure_licensing_test_roles(
    connection: psycopg.AsyncConnection,
    roles: tuple[str, ...] = ("fdai_core", "fdai_operator"),
) -> None:
    if connection.info.port != 5433 or connection.info.host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        pytest.fail("Licensing role bootstrap requires isolated loopback validation port 5433.")
    async with connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('fdai-licensing-test-role-bootstrap'))"
        )
        for role in roles:
            found = await connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if await found.fetchone() is None:
                await connection.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
                        sql.Identifier(role)
                    )
                )


async def test_licensing_fixture_bootstraps_absent_roles_without_widening_privileges(
    entitlement_database: str,
) -> None:
    suffix = uuid4().hex[:12]
    roles = (f"fdai_entitlement_core_{suffix}", f"fdai_entitlement_operator_{suffix}")
    created = False
    async with await psycopg.AsyncConnection.connect(
        entitlement_database, autocommit=True
    ) as connection:
        try:
            before = await connection.execute(
                "SELECT oid FROM pg_roles WHERE rolname = ANY(%s)", (list(roles),)
            )
            assert await before.fetchall() == []
            await _ensure_licensing_test_roles(connection, roles)
            created = True
            first = await connection.execute(
                "SELECT oid, rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(roles),),
            )
            records = await first.fetchall()
            assert len(records) == 2
            assert all(record[1:] == (False, False, False, False, False) for record in records)
            await _ensure_licensing_test_roles(connection, roles)
            second = await connection.execute(
                "SELECT oid FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname", (list(roles),)
            )
            assert await second.fetchall() == [(record[0],) for record in records]
        finally:
            if created:
                for role in roles:
                    await connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def store(dsn: str) -> PostgresAcceptedEntitlementStore:
    return PostgresAcceptedEntitlementStore(
        dsn=dsn, installation_binding=_INSTALLATION, deployment_binding=_DEPLOYMENT
    )


async def test_original_grant_and_audit_commit_once_and_survive_reader_reconstruction(
    entitlement_database: str,
) -> None:
    from dataclasses import replace

    authority, token, _key = signed_authority()
    writer = store(entitlement_database)
    assert await asyncio.to_thread(writer.read) is None
    receipt = await asyncio.to_thread(writer.accept, token, authority=authority, now=_NOW)
    duplicate = await asyncio.to_thread(writer.accept, token, authority=authority, now=_NOW)
    assert duplicate == receipt and token not in json.dumps(receipt.to_dict())
    reconstructed = store(entitlement_database)
    resolved = await asyncio.to_thread(
        replace(authority, token_source=reconstructed).resolve, now=_NOW
    )
    assert resolved.status is LicenseStatus.ACTIVE
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        for table in (
            "licensing_accepted_entitlement",
            "licensing_entitlement_acceptance_audit",
        ):
            cursor = await connection.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
            assert await cursor.fetchone() == (1,)
        cursor = await connection.execute("SELECT count(*) FROM licensing_trial")
        assert await cursor.fetchone() == (0,)


async def test_distinct_valid_token_cannot_replace_current_grant(
    entitlement_database: str,
) -> None:
    authority, token, key = signed_authority()
    writer = store(entitlement_database)
    receipt = await asyncio.to_thread(writer.accept, token, authority=authority, now=_NOW)
    changed_document = _claims(entitlement_id="ent-another").canonical_document()
    changed = _token(changed_document, key.sign(changed_document))
    with pytest.raises(EntitlementAcceptanceConflictError):
        await asyncio.to_thread(writer.accept, changed, authority=authority, now=_NOW)
    assert await asyncio.to_thread(writer.read) == token
    assert await asyncio.to_thread(writer.accept, token, authority=authority, now=_NOW) == receipt


async def test_concurrent_duplicate_imports_share_the_original_receipt(
    entitlement_database: str,
) -> None:
    authority, token, _key = signed_authority()
    barrier = threading.Barrier(4, timeout=10)

    def accept():
        barrier.wait()
        return store(entitlement_database).accept(token, authority=authority, now=_NOW)

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = await asyncio.gather(
            *(asyncio.get_running_loop().run_in_executor(executor, accept) for _ in range(4))
        )
    assert len(set(receipts)) == 1


@pytest.mark.parametrize("clock_blocked", [False, True])
async def test_import_preserves_existing_trial_anchor_revision_and_sticky_clock_state(
    entitlement_database: str, clock_blocked: bool
) -> None:
    authority, token, _key = signed_authority()
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        await connection.execute(
            """
            INSERT INTO licensing_trial
              (singleton, installation_binding, deployment_binding, activated_at,
               last_observed_at, revision, clock_blocked)
            VALUES (TRUE, %s, %s, %s, %s, 7, %s)
            """,
            (
                _INSTALLATION,
                _DEPLOYMENT,
                _NOW - timedelta(days=31),
                _NOW,
                clock_blocked,
            ),
        )
        cursor = await connection.execute("SELECT * FROM licensing_trial")
        before = await cursor.fetchone()
    await asyncio.to_thread(
        store(entitlement_database).accept, token, authority=authority, now=_NOW
    )
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        cursor = await connection.execute("SELECT * FROM licensing_trial")
        assert await cursor.fetchone() == before


async def test_core_token_and_audit_grants_are_read_insert_only(entitlement_database: str) -> None:
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        for table in ("licensing_accepted_entitlement", "licensing_entitlement_acceptance_audit"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cursor = await connection.execute(
                    "SELECT has_table_privilege('fdai_core', %s, %s)",
                    (table, privilege),
                )
                assert await cursor.fetchone() == (privilege in {"SELECT", "INSERT"},)
            cursor = await connection.execute(
                "SELECT has_table_privilege('fdai_operator', %s, 'SELECT')", (table,)
            )
            assert await cursor.fetchone() == (False,)


@pytest.mark.parametrize(
    "wrong_field", ["installation_binding", "deployment_binding", "distribution_id"]
)
async def test_signed_wrong_binding_never_creates_an_accepted_record(
    entitlement_database: str, wrong_field: str
) -> None:
    authority, _original, key = signed_authority()
    document = _claims(
        **{wrong_field: "another-distribution" if wrong_field == "distribution_id" else "f" * 64}
    ).canonical_document()
    token = _token(document, key.sign(document))
    with pytest.raises(ValueError, match="misbound"):
        await asyncio.to_thread(
            store(entitlement_database).accept, token, authority=authority, now=_NOW
        )
    assert await asyncio.to_thread(store(entitlement_database).read) is None


async def test_audit_failure_rolls_back_token_and_does_not_activate_trial(
    entitlement_database: str,
) -> None:
    authority, token, _key = signed_authority()
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        await connection.execute(
            """
            CREATE FUNCTION fail_acceptance_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic audit failure'; END; $$;
            CREATE TRIGGER fail_acceptance_audit BEFORE INSERT
              ON licensing_entitlement_acceptance_audit
              FOR EACH ROW EXECUTE FUNCTION fail_acceptance_audit();
            """
        )
    with pytest.raises(EntitlementSourceUnavailableError):
        await asyncio.to_thread(
            store(entitlement_database).accept, token, authority=authority, now=_NOW
        )
    assert await asyncio.to_thread(store(entitlement_database).read) is None
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        cursor = await connection.execute("SELECT count(*) FROM licensing_trial")
        assert await cursor.fetchone() == (0,)


async def test_missing_audit_and_retained_schema_rollback_fail_closed(
    entitlement_database: str,
) -> None:
    authority, token, _key = signed_authority()
    writer = store(entitlement_database)
    await asyncio.to_thread(writer.accept, token, authority=authority, now=_NOW)
    async with await psycopg.AsyncConnection.connect(entitlement_database) as connection:
        with pytest.raises(psycopg.Error, match="blocks schema rollback"):
            await connection.execute(migration_sql(downgrade=True))
        await connection.rollback()
        await connection.execute("DELETE FROM licensing_entitlement_acceptance_audit")
    with pytest.raises(EntitlementSourceUnavailableError):
        await asyncio.to_thread(writer.read)


async def test_true_fresh_producer_and_local_owner_importer_processes(
    entitlement_database: str, tmp_path: Path
) -> None:
    authority, token, issuer = signed_authority()
    recipient_key = X25519PrivateKey.generate()
    recipient = entitlement_recipient(
        recipient_key.public_key(),
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
    )
    os.chmod(tmp_path, 0o700)
    files = {
        "token": token.encode(),
        "recipient.pub": recipient_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        "recipient.key": recipient_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "issuer.pub": issuer.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.write_bytes(content)
        os.chmod(path, 0o600)
    environment = dict(os.environ)
    environment["FDAI_STATE_STORE_DSN"] = entitlement_database
    environment["PYTHONPATH"] = os.pathsep.join(
        str(ROOT / relative)
        for relative in (
            "services/core-control-plane/src",
            "packages/service-contracts/src",
            "packages/deployment-cli/src",
        )
    )
    producer = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "fdai_deployment_cli",
            "license",
            "seal-entitlement",
            "--token",
            str(tmp_path / "token"),
            "--recipient-public-key",
            str(tmp_path / "recipient.pub"),
            "--installation-binding",
            _INSTALLATION,
            "--deployment-binding",
            _DEPLOYMENT,
            "--destination",
            str(tmp_path / "carrier"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert producer.returncode == 0, producer.stderr
    assert json.loads(producer.stdout)["license_verified"] is False
    # This fresh process injects a synthetic issuer, never packaged production trust.
    child = (
        "import sys; from pathlib import Path; "
        "from fdai.delivery.trust import Ed25519LicenseVerifier; "
        "from fdai.delivery.licensing_entitlement_import import main; "
        "raise SystemExit(main(sys.argv[2:], verifier="
        "Ed25519LicenseVerifier(Path(sys.argv[1]).read_bytes())))"
    )
    arguments = [
        sys.executable,
        "-c",
        child,
        str(tmp_path / "issuer.pub"),
        "--carrier",
        str(tmp_path / "carrier"),
        "--recipient-key",
        str(tmp_path / "recipient.key"),
        "--recipient-fingerprint",
        recipient.fingerprint,
        "--installation-binding",
        _INSTALLATION,
        "--deployment-binding",
        _DEPLOYMENT,
    ]
    results = []
    for _ in range(2):
        result = await asyncio.to_thread(
            subprocess.run, arguments, env=environment, capture_output=True, text=True, timeout=20
        )
        assert result.returncode == 0, result.stderr
        assert token not in result.stdout + result.stderr
        results.append(json.loads(result.stdout))
    assert results[0] == results[1]
    assert results[0]["execution_authority"] is False
    assert await asyncio.to_thread(store(entitlement_database).read) == token
    inspected = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "fdai.delivery.licensing_entitlement_import",
            "--inspect",
            "--installation-binding",
            _INSTALLATION,
            "--deployment-binding",
            _DEPLOYMENT,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout) == results[0]
    assert token not in inspected.stdout + inspected.stderr
