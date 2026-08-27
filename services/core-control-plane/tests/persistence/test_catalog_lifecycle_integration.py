"""Live PostgreSQL lifecycle coverage for versioned rule lookup storage."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVICE_CONFIG = REPO_ROOT / "service-migrations" / "configs" / "core-control-plane.ini"
_CATALOG_LIFECYCLE_REVISION = "core_catalog_lifecycle_20260829"


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _run_legacy_upgrade(url: str) -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "FDAI_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"legacy alembic upgrade failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _run_service(*args: str, url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - controlled repository command
        [
            sys.executable,
            str(REPO_ROOT / "service-migrations" / "migrate.py"),
            "core-control-plane",
            *args,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "FDAI_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def _ensure_service_head(url: str) -> str:
    heads = _run_service("heads", url=url)
    assert heads.returncode == 0, f"unable to read service migration head: {heads.stderr}"
    head = heads.stdout.strip().splitlines()[-1].split()[0]
    upgrade = _run_service("upgrade", "head", url=url)
    if upgrade.returncode != 0 and "baseline is not stamped" in (upgrade.stdout + upgrade.stderr):
        pytest.skip("core-control-plane service migration baseline is not adopted")
    assert upgrade.returncode == 0, (
        f"service migration upgrade failed:\nstdout:\n{upgrade.stdout}\nstderr:\n{upgrade.stderr}"
    )
    current = _run_service("current", url=url)
    assert current.returncode == 0, f"unable to read service migration current: {current.stderr}"
    assert head in current.stdout, (
        f"service migration did not reach head {head!r}: {current.stdout}"
    )
    return head


def _downgrade_service(url: str, revision: str) -> None:
    downgrade = subprocess.run(  # noqa: S603 - controlled repository command
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(_SERVICE_CONFIG),
            "downgrade",
            revision,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "FDAI_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert downgrade.returncode == 0, (
        f"service migration rollback failed:\nstdout:\n{downgrade.stdout}\n"
        f"stderr:\n{downgrade.stderr}"
    )


def _service_predecessor(revision_id: str) -> str:
    revision = ScriptDirectory.from_config(Config(str(_SERVICE_CONFIG))).get_revision(revision_id)
    if revision is None or not isinstance(revision.down_revision, str):
        raise AssertionError(f"service migration {revision_id!r} has no single predecessor")
    return revision.down_revision


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(_plain_dsn(url))


def test_catalog_version_lifecycle_on_current_service_migration_head() -> None:
    """Prove version invalidation, TTL expiry, retention, and migration rollback."""
    url = _requires_live_db()
    _run_legacy_upgrade(url)
    head = _ensure_service_head(url)
    catalog_predecessor = _service_predecessor(_CATALOG_LIFECYCLE_REVISION)
    _downgrade_service(url, catalog_predecessor)
    prefix = uuid.uuid4().hex
    rule_id = f"lifecycle.rule.{prefix}"
    old_version = f"catalog-n-{prefix}"
    new_version = f"catalog-n-plus-one-{prefix}"
    old_signature = f"action-{prefix}"
    old_input = f"input-{prefix}"
    new_input = f"input-new-{prefix}"

    try:
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO learned_action
                    (rule_id, action_signature, action_payload)
                VALUES (%s, %s, '{"action":"retain"}'::jsonb)
                """,
                (rule_id, old_signature),
            )
            cur.execute(
                """
                INSERT INTO t2_cache
                    (catalog_version, input_hash, output, model)
                VALUES
                    (%s, %s, '{"answer":"legacy"}'::jsonb, 'test-model')
                """,
                (old_version, old_input),
            )
            conn.commit()

        upgrade = _run_service("upgrade", _CATALOG_LIFECYCLE_REVISION, url=url)
        assert upgrade.returncode == 0, (
            f"service migration upgrade failed:\nstdout:\n{upgrade.stdout}\nstderr:\n"
            f"{upgrade.stderr}"
        )
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT catalog_version FROM learned_action WHERE action_signature = %s",
                (old_signature,),
            )
            assert cur.fetchone() == ("legacy",), "legacy learned actions must be backfilled"
            cur.execute(
                """
                SELECT expires_at > created_at, expires_at > NOW()
                  FROM t2_cache
                 WHERE input_hash = %s
                """,
                (old_input,),
            )
            assert cur.fetchone() == (True, True), "legacy T2 rows must receive a live expiry"

            cur.execute(
                """
                INSERT INTO learned_action
                    (rule_id, action_signature, action_payload, catalog_version)
                VALUES (%s, %s, '{"action":"retain-new"}'::jsonb, %s)
                """,
                (rule_id, old_signature, new_version),
            )
            cur.execute(
                """
                SELECT COUNT(*) FROM learned_action
                 WHERE action_signature = %s
                   AND catalog_version IN (%s, %s)
                """,
                (old_signature, "legacy", new_version),
            )
            assert cur.fetchone() == (2,), "action signatures must be scoped by catalog version"

            cur.execute(
                """
                SELECT COUNT(*) FROM t2_cache
                 WHERE catalog_version = %s AND expires_at > NOW()
                """,
                (new_version,),
            )
            assert cur.fetchone() == (0,), "a catalog bump must not reuse the prior T2 entry"

            cur.execute(
                "UPDATE t2_cache SET expires_at = NOW() - INTERVAL '1 second' "
                "WHERE input_hash = %s",
                (old_input,),
            )
            cur.execute(
                """
                SELECT COUNT(*) FROM t2_cache
                 WHERE catalog_version = %s AND expires_at > NOW()
                """,
                (old_version,),
            )
            assert cur.fetchone() == (0,), "expired T2 entries must be unreadable"

            cur.execute(
                """
                INSERT INTO t2_cache
                    (catalog_version, input_hash, output, model, expires_at)
                VALUES
                    (%s, %s, '{"answer":"current"}'::jsonb, 'test-model',
                            NOW() + INTERVAL '1 hour')
                """,
                (new_version, new_input),
            )
            cur.execute(
                """
                SELECT COUNT(*) FROM t2_cache
                 WHERE catalog_version = %s AND expires_at > NOW()
                """,
                (new_version,),
            )
            assert cur.fetchone() == (1,)

            cur.execute(
                """
                SELECT COUNT(*) FROM learned_action
                 WHERE action_signature = %s AND catalog_version = %s
                """,
                (old_signature, "legacy"),
            )
            assert cur.fetchone() == (1,), "catalog invalidation must retain learned actions"

        downgrade = subprocess.run(  # noqa: S603 - controlled repository command
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(_SERVICE_CONFIG),
                "downgrade",
                catalog_predecessor,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "FDAI_DATABASE_URL": url},
            capture_output=True,
            text=True,
            check=False,
        )
        assert downgrade.returncode != 0, "downgrade must refuse cross-version duplicates"
        assert "resolve collisions before rollback" in (downgrade.stdout + downgrade.stderr)

        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                  FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name IN ('learned_action', 't2_cache')
                   AND column_name IN ('catalog_version', 'expires_at')
                """
            )
            assert set(cur.fetchall()) == {
                ("learned_action", "catalog_version"),
                ("t2_cache", "catalog_version"),
                ("t2_cache", "expires_at"),
            }, "refused rollback must preserve version-aware lifecycle columns"
    finally:
        restore = _run_service("upgrade", "head", url=url)
        assert restore.returncode == 0, (
            f"failed to restore service migration head {head}:\n"
            f"stdout:\n{restore.stdout}\nstderr:\n{restore.stderr}"
        )
        with _connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM learned_action WHERE action_signature = %s",
                (old_signature,),
            )
            cur.execute(
                "DELETE FROM t2_cache WHERE input_hash IN (%s, %s)",
                (old_input, new_input),
            )
