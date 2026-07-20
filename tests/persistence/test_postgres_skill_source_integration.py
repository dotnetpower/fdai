from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.core.supply_chain.skill_quarantine import (
    QuarantinedSkillArtifact,
    QuarantinedSkillFile,
    SkillQuarantineState,
    SkillRevocation,
    SkillSourceRefreshState,
    SkillUpdateCandidate,
    quarantine_artifact_digest,
)
from fdai.delivery.persistence.postgres_skill_quarantine import (
    PostgresSkillQuarantineStore,
    PostgresSkillRevocationStore,
    PostgresSkillSourceRevoker,
    PostgresSkillUpdateCandidateStore,
)
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceRefreshStateStore,
    PostgresSkillSourceStore,
    PostgresSkillSourceStoreConfig,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _database_url() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


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
async def test_skill_source_records_survive_restart_and_revocation_keeps_provenance() -> None:
    dsn = _database_url()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    source = SkillSource(
        source_id=f"skill-source-{suffix}",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example-org/skills",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills/example",
        authentication_audience_ref="FDAI_GITHUB_TOKEN",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3600,
        enabled=True,
    )
    content = b"Reviewed skill content"
    file = QuarantinedSkillFile(
        path="skills/example/SKILL.md",
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        media_type="text/markdown",
    )
    artifact = QuarantinedSkillArtifact(
        quarantine_id=f"quarantine-{suffix}",
        source_id=source.source_id,
        source_revision="a" * 40,
        artifact_digest=quarantine_artifact_digest((file,)),
        files=(file,),
        publisher_signature=b"s" * 64,
        fetched_at=NOW,
        state=SkillQuarantineState.PROPOSED,
    )
    candidate = SkillUpdateCandidate(
        candidate_id=f"candidate-{suffix}",
        quarantine_id=artifact.quarantine_id,
        artifact_digest=artifact.artifact_digest,
        prior_installed_digest=None,
        created_at=NOW,
    )
    revocation = SkillRevocation(
        revocation_id=f"revocation-{suffix}",
        source_id=source.source_id,
        artifact_digest=artifact.artifact_digest,
        reason="Publisher key was withdrawn.",
        revoked_at=NOW,
    )
    config = PostgresSkillSourceStoreConfig(dsn=dsn)
    sources = PostgresSkillSourceStore(config=config)
    quarantine = PostgresSkillQuarantineStore(config=config)
    candidates = PostgresSkillUpdateCandidateStore(config=config)
    revocations = PostgresSkillRevocationStore(config=config)
    states = PostgresSkillSourceRefreshStateStore(config=config)
    trusted = PostgresTrustedArtifactStore(config=PostgresTrustedArtifactStoreConfig(dsn=dsn))
    trusted_bytes = b"trusted installed skill"
    trusted_record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id=f"example.skill.{suffix}",
        version="1.0.0",
        source=source.source_id,
        content_sha256=hashlib.sha256(trusted_bytes).hexdigest(),
        artifact=trusted_bytes,
        signature=b"s" * 64,
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )

    assert await sources.put(source, now=NOW) == source
    assert await quarantine.put(artifact) == artifact
    assert await candidates.put(candidate) == candidate
    state = SkillSourceRefreshState(
        source_id=source.source_id,
        last_refresh_at=NOW,
        next_refresh_at=NOW + timedelta(hours=1),
        last_etag='"v1"',
    )
    assert await states.put(state) == state
    assert await revocations.put(revocation) == revocation
    assert await trusted.put(trusted_record, expected_revision=0) == trusted_record

    restarted_quarantine = PostgresSkillQuarantineStore(config=config)
    restarted_candidates = PostgresSkillUpdateCandidateStore(config=config)
    assert await restarted_quarantine.get(artifact.quarantine_id) == artifact
    assert await restarted_candidates.get(candidate.candidate_id) == candidate
    assert await states.get(source.source_id) == state
    assert await revocations.is_revoked(
        source_id=source.source_id,
        artifact_digest=artifact.artifact_digest,
    )

    result = await PostgresSkillSourceRevoker(config=config).revoke_source(
        source_id=source.source_id,
        reason="Publisher key was withdrawn.",
        revoked_at=NOW + timedelta(minutes=1),
    )
    assert result.disabled_artifact_ids == (trusted_record.artifact_id,)
    restarted_source = await PostgresSkillSourceStore(config=config).get(source.source_id)
    assert restarted_source is not None and restarted_source.enabled is False
    retained = await restarted_quarantine.get(artifact.quarantine_id)
    assert retained is not None
    assert retained.state is SkillQuarantineState.REVOKED
    assert retained.files == artifact.files
    retained_trusted = await trusted.get(TrustedArtifactKind.SKILL, trusted_record.artifact_id)
    assert retained_trusted is not None
    assert retained_trusted.state is TrustedArtifactState.DISABLED
    assert retained_trusted.artifact == trusted_bytes
    assert len(await revocations.list(source_id=source.source_id)) >= 2
