from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATION = REPO_ROOT / "alembic/versions/20260813_0080_catalog_generation_manifest.py"


def test_catalog_generation_manifest_migration_is_bounded_and_fail_closed() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    upgrade, downgrade = migration.split("def downgrade()", maxsplit=1)

    assert "document_count BETWEEN 1 AND 20000" in upgrade
    assert "= (document_count + 255) / 256" in upgrade
    assert "inline_document_digests = '[]'::jsonb" in upgrade
    assert "ordinal BETWEEN 0 AND 19999" in upgrade
    assert "DELETE FROM" not in upgrade
    assert "TRUNCATE" not in upgrade
    assert "manifest downgrade requires" in downgrade
    assert "an empty generation store" in downgrade
    assert downgrade.index("IF EXISTS") < downgrade.index("DROP COLUMN")


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    source = os.environ.get("FDAI_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_DATABASE_URL is unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    params = conninfo_to_dict(source)
    database = "fdai_manifest_migration_" + uuid4().hex[:12]
    admin_params = dict(params)
    admin_params["dbname"] = "postgres"
    try:
        admin = psycopg.connect(make_conninfo(**admin_params), autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("FDAI_DATABASE_URL principal cannot create a disposable database")
    try:
        yield urlunsplit(parts._replace(path=f"/{database}"))
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
        )
        admin.close()


def _alembic(database_url: str, revision: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["FDAI_DATABASE_URL"] = database_url
    return subprocess.run(  # noqa: S603 - fixed repository migration command
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _downgrade(database_url: str, revision: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["FDAI_DATABASE_URL"] = database_url
    return subprocess.run(  # noqa: S603 - fixed repository migration command
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.integration
def test_catalog_generation_manifest_migration_preserves_nonempty_history(
    disposable_database_url: str,
) -> None:
    assert _alembic(disposable_database_url, "20260808_0079").returncode == 0
    digest = "sha256:" + ("a" * 64)
    with psycopg.connect(disposable_database_url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO catalog_search_generation "
            "(generation_id, generation_digest, corpus, catalog_digest, "
            "semantic_schema_digest, ontology_release_digest, embedding_space_id, "
            "embedding_model_version, embedding_dimension, state, "
            "validation_receipt_digest, document_count) "
            "VALUES (%s, %s, 'active', %s, %s, %s, 'test-space', "
            "'test-model', 384, 'staged', %s, 1)",
            ("pre-manifest", digest, digest, digest, digest, digest),
        )

    blocked_upgrade = _alembic(disposable_database_url, "20260813_0080")
    assert blocked_upgrade.returncode != 0
    assert "manifest migration requires an empty generation store" in blocked_upgrade.stderr
    with psycopg.connect(disposable_database_url, autocommit=True) as connection:
        assert connection.execute("SELECT count(*) FROM catalog_search_generation").fetchone() == (
            1,
        )
        connection.execute("DELETE FROM catalog_search_generation")

    assert _alembic(disposable_database_url, "20260813_0080").returncode == 0
    with psycopg.connect(disposable_database_url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO catalog_search_generation "
            "(generation_id, generation_digest, corpus, catalog_digest, "
            "semantic_schema_digest, ontology_release_digest, embedding_space_id, "
            "embedding_model_version, embedding_dimension, state, "
            "validation_receipt_digest, document_count, document_digest_root, "
            "document_digest_chunks, inline_document_digests) "
            "VALUES (%s, %s, 'active', %s, %s, %s, 'test-space', "
            "'test-model', 384, 'staged', %s, 1, %s, %s::jsonb, %s::jsonb)",
            (
                "manifest-aware",
                digest,
                digest,
                digest,
                digest,
                digest,
                digest,
                '[{"index": 0, "document_count": 1, "document_digest_root": "' + digest + '"}]',
                '["' + digest + '"]',
            ),
        )

    blocked_downgrade = _downgrade(disposable_database_url, "20260808_0079")
    assert blocked_downgrade.returncode != 0
    assert "manifest downgrade requires an empty generation store" in blocked_downgrade.stderr
    with psycopg.connect(disposable_database_url, autocommit=True) as connection:
        assert connection.execute("SELECT count(*) FROM catalog_search_generation").fetchone() == (
            1,
        )
        connection.execute("DELETE FROM catalog_search_generation")

    assert _downgrade(disposable_database_url, "20260808_0079").returncode == 0
