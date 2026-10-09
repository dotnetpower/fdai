"""Exercise code-security privileges on the isolated validation PostgreSQL, never runtime."""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_code_security_scan_requests import (
    PostgresCodeSecurityScanRequestQueue,
    PostgresCodeSecurityScanRequestQueueConfig,
)
from fdai.delivery.persistence.postgres_code_security_state import PostgresCodeSecurityStateStore
from fdai.delivery.persistence.state_store_code_security_repository import (
    list_repositories,
    register_repository,
    set_repository_enabled,
)
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash
from psycopg import sql
from psycopg.conninfo import make_conninfo

_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION = _ROOT / (
    "service-migrations/branches/core-control-plane/versions/20261009_core_code_security_role.py"
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    raw = os.environ.get("FDAI_DATABASE_URL")
    if not raw:
        pytest.skip("requires the isolated local validation database wrapper")
    parsed = urlsplit(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.port != 5433:
        pytest.fail("restricted role tests require loopback validation PostgreSQL on port 5433")
    name = "fdai_security_privileges_" + uuid4().hex[:12]
    admin = urlunsplit(parsed._replace(path="/postgres"))
    dsn = urlunsplit(parsed._replace(path="/" + name))
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("""
                CREATE TABLE state_kv(key TEXT PRIMARY KEY, value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
                CREATE TABLE audit_log(seq BIGSERIAL PRIMARY KEY, event_id UUID,
                    correlation_id TEXT, actor TEXT, action_kind TEXT, mode TEXT,
                    entry JSONB, previous_hash TEXT, entry_hash TEXT);
                INSERT INTO state_kv(key,value) VALUES
                    ('unrelated:private', '{"secret":"must-not-be-readable"}');
            """)
            spec = importlib.util.spec_from_file_location("security_role_migration", _MIGRATION)
            assert spec is not None and spec.loader is not None
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            monkeypatch.setattr(migration.op, "execute", connection.execute)
            migration.upgrade()
        restricted = make_conninfo(dsn, options="-c role=fdai_code_security_worker")
        yield dsn, restricted
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


async def test_restricted_store_records_registration_and_cas_with_valid_chain(
    database: tuple[str, str],
) -> None:
    admin, restricted = database
    store = PostgresCodeSecurityStateStore(config=PostgresStateStoreConfig(dsn=restricted))
    try:
        repo, created = await register_repository(
            store, alias="example-app", location="example/app", registered_by="owner"
        )
        assert created and repo.enabled
        assert (await list_repositories(store))[0].repository_alias == "example-app"
        disabled = await set_repository_enabled(store, "example-app", enabled=False, actor="owner")
        assert disabled.revision == 2 and not disabled.enabled
        await store.append_audit_entry(
            {
                "kind": "code_security_repository_changed",
                "producer_principal": "Heimdall",
                "change": "knowledge_connected",
                "repository_alias": "example-app",
                "provider": "github",
                "enabled": False,
                "registration_revision": 2,
                "actor": "owner",
                "execution_authority": False,
            }
        )
        assert not await store.compare_and_set_state(
            "runtime:code-security-repository:example-app", {}, expected_revision=1
        )
        await store.write_state(
            "runtime:code-security-schedule:cursor", {"last_repository_alias": "example-app"}
        )
        assert await store.read_state("runtime:code-security-schedule:cursor") == {
            "last_repository_alias": "example-app"
        }
    finally:
        await store.aclose()
    with psycopg.connect(admin) as connection:
        rows = connection.execute(
            "SELECT entry, previous_hash, entry_hash FROM audit_log ORDER BY seq"
        ).fetchall()
    assert len(rows) == 3
    previous = GENESIS_HASH
    for entry, previous_hash, entry_hash in rows:
        assert previous_hash == previous and entry_hash == next_hash(previous, entry)
        previous = entry_hash


async def test_restricted_store_has_no_unrelated_state_or_direct_table_access(
    database: tuple[str, str],
) -> None:
    _, restricted = database
    with psycopg.connect(restricted, autocommit=True) as connection:
        for query in (
            "SELECT * FROM public.state_kv",
            "UPDATE public.state_kv SET value='{}'",
            "SELECT * FROM public.audit_log",
            "SELECT public.fdai_code_security_state_read('unrelated:private')",
            "SELECT * FROM public.fdai_code_security_states('runtime:', 100)",
            "SELECT public.fdai_code_security_state_write("
            "'unrelated:private', '{}', 'insert', NULL)",
            "SELECT public.fdai_code_security_state_write("
            "'runtime:code-security-review:example:a', '{}', 'upsert', NULL)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(query)
        assert (
            connection.execute("SELECT current_user").fetchone()[0] == "fdai_code_security_worker"
        )


async def test_audit_failure_rolls_back_registration_write(database: tuple[str, str]) -> None:
    _, restricted = database
    store = PostgresCodeSecurityStateStore(config=PostgresStateStoreConfig(dsn=restricted))
    key = "runtime:code-security-repository:rejected"
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await store.write_state_with_audit_if_absent(
                key, {"revision": 1}, {"kind": "unrelated", "execution_authority": True}
            )
        assert await store.read_state(key) is None
        await store.write_state_if_absent("runtime:code-security-review:example:a", {"x": 1})
        assert not await store.write_state_if_absent(
            "runtime:code-security-review:example:a", {"x": 2}
        )
    finally:
        await store.aclose()


async def test_inherited_operations_cannot_reuse_elevated_login_permissions(
    database: tuple[str, str],
) -> None:
    admin, _ = database
    store = PostgresCodeSecurityStateStore(config=PostgresStateStoreConfig(dsn=admin))
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await store.verify_chain()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await store.read_state("unrelated:private")
        assert await store.read_state("runtime:code-security-schedule:missing") is None
    finally:
        await store.aclose()


async def test_restricted_claim_and_close_cannot_touch_other_outbox_operations(
    database: tuple[str, str],
) -> None:
    admin, restricted = database
    with psycopg.connect(admin, autocommit=True) as connection:
        for suffix, operation in (
            ("other", "unrelated.action"),
            ("scan", "code_security.scan_request"),
        ):
            connection.execute(
                "INSERT INTO state_kv(key,value) VALUES (%s,%s::jsonb)",
                (
                    "operator-proposal:operations:" + suffix,
                    json.dumps(
                        {
                            "family": "operations",
                            "operation": operation,
                            "dispatch_status": "pending",
                            "accepted_at": "2026-10-09T00:00:00Z",
                            "proposal_id": "operator-" + "a" * 32,
                        }
                    ),
                ),
            )
    queue = PostgresCodeSecurityScanRequestQueue(
        PostgresCodeSecurityScanRequestQueueConfig(dsn=restricted, restricted_access=True)
    )
    claim = await queue.claim()
    assert claim is not None and claim.key.endswith(":scan")
    assert not await queue.mark_completed(key=claim.key, claim_id="wrong", result={})
    assert await queue.mark_rejected(
        key=claim.key, claim_id=claim.claim_id, reason_code="request_malformed"
    )
    assert not await queue.mark_rejected(
        key=claim.key, claim_id=claim.claim_id, reason_code="request_malformed"
    )
    assert await queue.claim() is None
    with psycopg.connect(restricted, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT public.fdai_code_security_close(%s,%s,%s::jsonb)",
                (claim.key, claim.claim_id, json.dumps({"operation": "unrelated.action"})),
            )
    with psycopg.connect(admin) as connection:
        other = connection.execute(
            "SELECT value FROM state_kv WHERE key='operator-proposal:operations:other'"
        ).fetchone()[0]
    assert other["dispatch_status"] == "pending"


def test_capabilities_are_not_public_and_invalid_parameters_fail_closed(
    database: tuple[str, str],
) -> None:
    admin, restricted = database
    with psycopg.connect(admin) as connection:
        public_execute = connection.execute("""
            SELECT COUNT(*) FROM pg_proc AS proc,
                LATERAL aclexplode(proc.proacl) AS acl
            WHERE proc.proname LIKE 'fdai_code_security_%'
                AND acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
        """).fetchone()[0]
    assert public_execute == 0
    with psycopg.connect(restricted, autocommit=True) as connection:
        for query in (
            "SELECT * FROM public.fdai_code_security_states(NULL, 1)",
            "SELECT * FROM public.fdai_code_security_states('runtime:code-security-review:', 1001)",
            "SELECT public.fdai_code_security_state_write("
            "'runtime:code-security-repository:x', '[]', 'insert', NULL)",
            "SELECT public.fdai_code_security_state_write("
            "'runtime:code-security-repository:x', '{}', NULL, NULL)",
            "SELECT public.fdai_code_security_state_write("
            "'runtime:code-security-repository:x', '{}', 'cas', -1)",
            "SELECT * FROM public.fdai_code_security_claim('claim', 'worker', 1)",
        ):
            with pytest.raises(psycopg.Error):
                connection.execute(query)


def test_downgrade_removes_capabilities_without_deleting_shared_state(
    database: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, restricted = database
    spec = importlib.util.spec_from_file_location("security_role_rollback", _MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with psycopg.connect(admin, autocommit=True) as connection:
        monkeypatch.setattr(migration.op, "execute", connection.execute)
        migration.downgrade()
        assert (
            connection.execute(
                "SELECT value FROM state_kv WHERE key='unrelated:private'"
            ).fetchone()
            is not None
        )
    with psycopg.connect(restricted, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.UndefinedFunction):
            connection.execute(
                "SELECT public.fdai_code_security_state_read('runtime:code-security-review:x')"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT value FROM state_kv")
