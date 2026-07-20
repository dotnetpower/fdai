"""PostgreSQL trusted extension/skill artifact persistence tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.core.skills import SkillCatalog, parse_skill_markdown, skill_body_digest
from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactInstaller,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    load_skill_catalog,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from fdai.delivery.trust import (
    Ed25519SkillTrustVerifier,
    Ed25519SkillTrustVerifierFactory,
    skill_signature_payload,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _record(artifact_id: str, kind: TrustedArtifactKind) -> TrustedArtifactRecord:
    return TrustedArtifactRecord(
        kind=kind,
        artifact_id=artifact_id,
        version="1.0.0",
        source="publisher.example",
        content_sha256="a" * 64,
        artifact=b"trusted artifact",
        signature=b"s" * 64,
        state=TrustedArtifactState.DISABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _skill_bundle(name: str, reference_path: str, reference_content: bytes) -> bytes:
    body = "Use durable inventory evidence."
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Durable restart test skill",
        "source": "publisher.example",
        "body_sha256": skill_body_digest(body),
        "required_tools": ["inventory.read"],
        "allowed_agents": ["Bragi"],
        "references": [
            {
                "path": reference_path,
                "sha256": hashlib.sha256(reference_content).hexdigest(),
                "size_bytes": len(reference_content),
                "media_type": "text/plain",
            }
        ],
    }
    return f"---\n{yaml.safe_dump(manifest, sort_keys=False)}---\n{body}\n".encode()


def test_config_and_revision_validation() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresTrustedArtifactStoreConfig(dsn="")
    store = PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(dsn="postgresql://example")
    )
    with pytest.raises(ValueError, match="expected_revision"):
        import asyncio

        asyncio.run(
            store.put(
                _record("example.skill", TrustedArtifactKind.SKILL),
                expected_revision=1,
            )
        )


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_artifacts_survive_restart_and_updates_are_revision_cas() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    extension = _record(f"example.extension.{suffix}", TrustedArtifactKind.EXTENSION)
    skill = _record(f"example.skill.{suffix}", TrustedArtifactKind.SKILL)
    config = PostgresTrustedArtifactStoreConfig(dsn=dsn)
    store = PostgresTrustedArtifactStore(config=config)
    assert await store.put(extension, expected_revision=0) == extension
    assert await store.put(skill, expected_revision=0) == skill
    enabled = replace(
        extension,
        state=TrustedArtifactState.ENABLED,
        revision=2,
        updated_at=datetime(2026, 7, 17, 12, 1, tzinfo=UTC),
    )
    assert await store.put(enabled, expected_revision=1) == enabled
    with pytest.raises(TrustedArtifactConflictError):
        await store.put(enabled, expected_revision=1)

    restarted = PostgresTrustedArtifactStore(config=config)
    assert await restarted.get(extension.kind, extension.artifact_id) == enabled
    assert skill in await restarted.list(TrustedArtifactKind.SKILL)


@pytest.mark.integration
async def test_skill_bundle_restart_loader_retains_reference_and_enabled_state() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    skill_name = f"restart.skill.{suffix}"
    reference_path = "references/inventory.txt"
    reference_content = b"durable inventory evidence"
    raw = _skill_bundle(skill_name, reference_path, reference_content)
    parsed = parse_skill_markdown(raw)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = private_key.sign(skill_signature_payload(parsed, raw))
    config = PostgresTrustedArtifactStoreConfig(dsn=dsn)
    store = PostgresTrustedArtifactStore(config=config)
    installer = TrustedArtifactInstaller(store=store)
    await installer.install_skill(
        SkillCatalog(),
        raw,
        references={reference_path: reference_content},
        signature=signature,
        verifier=Ed25519SkillTrustVerifier(
            trusted_publishers={parsed.manifest.source: public_key},
            signature=signature,
        ),
        now=_NOW,
    )
    installed = await store.get(TrustedArtifactKind.SKILL, skill_name)
    assert installed is not None
    enabled = replace(
        installed,
        state=TrustedArtifactState.ENABLED,
        revision=2,
        updated_at=datetime(2026, 7, 17, 12, 1, tzinfo=UTC),
    )
    await store.put(enabled, expected_revision=1)

    restarted = PostgresTrustedArtifactStore(config=config)
    listed = await restarted.list(TrustedArtifactKind.SKILL)
    target_records = tuple(record for record in listed if record.artifact_id == skill_name)
    catalog = load_skill_catalog(
        target_records,
        Ed25519SkillTrustVerifierFactory({parsed.manifest.source: public_key}),
        frozenset({"inventory.read"}),
        frozenset({"Bragi"}),
    )

    loaded = catalog.get(skill_name)
    assert loaded.enabled is True
    assert loaded.references[0].manifest.path == reference_path
    assert loaded.references[0].content == reference_content
