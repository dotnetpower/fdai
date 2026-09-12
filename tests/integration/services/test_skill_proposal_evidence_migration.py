"""Verify Operator evidence migration compatibility with the adopted legacy schema."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fdai.core.skills import SkillProposal
from fdai.delivery.persistence import PostgresSkillProposalStore, PostgresSkillProposalStoreConfig
from psycopg import sql

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
_OPERATOR_CONFIG = "service-migrations/configs/operator-service.ini"
_PREVIOUS_REVISION = "operator_conversation_policy_evidence_20260907"
_EVIDENCE_REVISION = "operator_skill_proposal_evidence_20260912"


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL") or os.environ.get("FDAI_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL and FDAI_DATABASE_URL are unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_skill_evidence_" + uuid4().hex[:12]
    with psycopg.connect(source, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            monkeypatch.setenv("FDAI_DATABASE_URL", urlunsplit(parts._replace(path=f"/{database}")))
            yield
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _run(*arguments: str) -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository migration commands
        [sys.executable, *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _evidence_column(connection: psycopg.Connection[tuple[object, ...]]) -> object:
    return connection.execute(
        """
        SELECT data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'skill_proposal'
          AND column_name = 'evidence_refs'
        """
    ).fetchone()


async def test_operator_round_trip_preserves_legacy_evidence_column(
    disposable_database: None,
    tmp_path: Path,
) -> None:
    _run("-m", "alembic", "upgrade", "head")
    config = PostgresSkillProposalStoreConfig(dsn=os.environ["FDAI_DATABASE_URL"])
    markdown = b"---\nname: example\n---\nReview bounded incident evidence.\n"
    proposal = SkillProposal(
        proposal_id="skill-proposal:rollback-evidence",
        skill_name="example",
        content_hash=sha256(markdown).hexdigest(),
        markdown=markdown,
        proposed_by_agent="Bragi",
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        evidence_refs=("audit:1", "audit:2"),
    )
    await PostgresSkillProposalStore(config=config).create(proposal)
    with psycopg.connect(os.environ["FDAI_DATABASE_URL"], autocommit=True) as connection:
        baseline_column = _evidence_column(connection)
        assert baseline_column == ("jsonb", "NO", "'[]'::jsonb")
        for service in ("core-control-plane", "document-ingestion-api", "operator-service"):
            _run(
                "service-migrations/migrate.py",
                service,
                "bootstrap",
                "--evidence-output",
                str(tmp_path / f"{service}.json"),
                "--schema-output",
                str(tmp_path / f"{service}-schema.json"),
                "--rollback-reference",
                "issue-815-local-round-trip",
            )
        assert _evidence_column(connection) == baseline_column
        _run("-m", "alembic", "-c", _OPERATOR_CONFIG, "downgrade", _PREVIOUS_REVISION)
        assert _evidence_column(connection) == baseline_column
        assert await PostgresSkillProposalStore(config=config).get(proposal.proposal_id) == proposal
        _run("-m", "alembic", "-c", _OPERATOR_CONFIG, "upgrade", _EVIDENCE_REVISION)
        assert _evidence_column(connection) == baseline_column
        assert await PostgresSkillProposalStore(config=config).get(proposal.proposal_id) == proposal
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("UPDATE skill_proposal SET evidence_refs = '{}'::jsonb")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20260912_0090",
        )
