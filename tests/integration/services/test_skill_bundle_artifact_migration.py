"""PostgreSQL migration coverage for governed skill bundle artifacts."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fdai.core.skills import (
    RuntimeSkill,
    RuntimeSkillBundle,
    encode_skill_bundle_manifest,
    skill_body_digest,
)
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedSkillBundleLoadError,
    load_skill_bundle_catalog,
    load_skill_catalog,
)
from fdai.delivery.persistence import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from psycopg import sql

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "20260720_0042"
_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return skill.raw_markdown == raw_markdown


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


class _SkillVerifierFactory:
    def __call__(self, record: TrustedArtifactRecord, /) -> _SkillVerifier:
        if record.signature != b"s" * 64:
            raise ValueError("skill signature is not trusted")
        return _SkillVerifier()


class _BundleVerifierFactory:
    def __call__(self, record: TrustedArtifactRecord, /) -> _BundleVerifier:
        if record.signature != b"b" * 64:
            raise ValueError("bundle signature is not trusted")
        return _BundleVerifier()


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    source = os.environ.get("FDAI_VALIDATION_DATABASE_URL") or os.environ.get("FDAI_DATABASE_URL")
    if not source:
        pytest.skip("FDAI_VALIDATION_DATABASE_URL and FDAI_DATABASE_URL are unset")
    source = source.replace("postgresql+psycopg://", "postgresql://", 1)
    parts = urlsplit(source)
    database = "fdai_skill_bundle_" + uuid4().hex[:12]
    with psycopg.connect(source, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        dsn = urlunsplit(parts._replace(path=f"/{database}"))
        try:
            monkeypatch.setenv("FDAI_DATABASE_URL", dsn)
            yield dsn
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _run_alembic_revision() -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository migration command
        [sys.executable, "-m", "alembic", "upgrade", _REVISION],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, "alembic upgrade to skill bundle artifacts failed"


def _skill_markdown() -> bytes:
    body = "Collect inventory evidence."
    return f"""---
name: inventory-evidence
version: 1.0.0
description: Inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()


def _skill_record() -> TrustedArtifactRecord:
    raw = _skill_markdown()
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id="inventory-evidence",
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=b"s" * 64,
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _bundle_artifact() -> bytes:
    return encode_skill_bundle_manifest(
        {
            "name": "incident-evidence-pack",
            "version": "1.0.0",
            "description": "Reviewed incident evidence procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": "Use the member exactly once.",
        }
    )


def _bundle_record(
    *,
    state: TrustedArtifactState,
    revision: int,
) -> TrustedArtifactRecord:
    raw = _bundle_artifact()
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL_BUNDLE,
        artifact_id="incident-evidence-pack",
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=b"b" * 64,
        state=state,
        revision=revision,
        created_at=_NOW,
        updated_at=_NOW,
    )


async def test_skill_bundle_artifacts_survive_restart_and_reject_tampering(
    disposable_database: str,
) -> None:
    _run_alembic_revision()
    store = PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(dsn=disposable_database)
    )
    skill_record = _skill_record()
    installed = _bundle_record(state=TrustedArtifactState.DISABLED, revision=1)
    enabled = replace(installed, state=TrustedArtifactState.ENABLED, revision=2)
    disabled = replace(installed, state=TrustedArtifactState.DISABLED, revision=3)
    reenabled = replace(installed, state=TrustedArtifactState.ENABLED, revision=4)

    assert await store.put(skill_record, expected_revision=0) == skill_record
    assert await store.put(installed, expected_revision=0) == installed
    assert await store.put(enabled, expected_revision=1) == enabled
    assert await store.put(disabled, expected_revision=2) == disabled
    assert await store.put(reenabled, expected_revision=3) == reenabled

    restarted = PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(dsn=disposable_database)
    )
    skills = load_skill_catalog(
        await restarted.list(TrustedArtifactKind.SKILL),
        _SkillVerifierFactory(),
        frozenset({"query_inventory"}),
        frozenset({"Bragi"}),
    )
    bundles = load_skill_bundle_catalog(
        await restarted.list(TrustedArtifactKind.SKILL_BUNDLE),
        _BundleVerifierFactory(),
        skills=skills,
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
    )

    assert skills.get("inventory-evidence").enabled is True
    restored_bundle = bundles.get("incident-evidence-pack")
    assert restored_bundle.enabled is True
    assert restored_bundle.manifest.members[0].name == "inventory-evidence"

    with psycopg.connect(disposable_database, autocommit=True) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            _REVISION,
        )
        connection.execute(
            """
            UPDATE trusted_artifact
               SET content_sha256 = %s
             WHERE artifact_kind = %s AND artifact_id = %s
            """,
            ("0" * 64, TrustedArtifactKind.SKILL_BUNDLE.value, "incident-evidence-pack"),
        )

    with pytest.raises(TrustedSkillBundleLoadError, match="digest"):
        load_skill_bundle_catalog(
            await restarted.list(TrustedArtifactKind.SKILL_BUNDLE),
            _BundleVerifierFactory(),
            skills=skills,
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
