from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.core.skills import SkillCatalog, skill_body_digest
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain import (
    TrustedArtifactInstaller,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.core.supply_chain.skill_quarantine import (
    DeterministicSkillScanner,
    InMemorySkillQuarantineStore,
    InMemorySkillUpdateCandidateStore,
    QuarantinedSkillArtifact,
    QuarantinedSkillFile,
    SkillQuarantineState,
    SkillUpdateCandidate,
    quarantine_artifact_digest,
)
from fdai.core.supply_chain.skill_source_admin import (
    SkillSourceAdministrationService,
    SkillSourceRevocationResult,
)
from fdai.core.supply_chain.skill_source_pipeline import SkillSourceRefreshService

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _source() -> SkillSource:
    return SkillSource(
        source_id="operations-skills",
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


def _markdown() -> bytes:
    body = "Use deterministic evidence."
    return (
        "---\n"
        "name: example.skill\n"
        "version: 1.0.0\n"
        "description: Example skill.\n"
        "source: operations-skills\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        "---\n"
        f"{body}\n"
    ).encode()


class Sources:
    async def get(self, source_id: str):  # type: ignore[no-untyped-def]
        return _source() if source_id == _source().source_id else None


class Revocations:
    async def is_revoked(self, **_kwargs) -> bool:  # type: ignore[no-untyped-def]
        return False


class Allow:
    def verify(self, _skill, _raw):  # type: ignore[no-untyped-def]
        return True


class ArtifactStore:
    def __init__(self) -> None:
        self.records: list[TrustedArtifactRecord] = []

    async def put(self, record, *, expected_revision):  # type: ignore[no-untyped-def]
        assert expected_revision == 0
        self.records.append(record)
        return record


class Revoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime]] = []

    async def revoke_source(
        self, *, source_id: str, reason: str, revoked_at: datetime
    ) -> SkillSourceRevocationResult:
        self.calls.append((source_id, reason, revoked_at))
        return SkillSourceRevocationResult(
            source_id=source_id,
            revoked_digests=("a" * 64,),
            disabled_artifact_ids=("example.skill",),
        )


async def _service():  # type: ignore[no-untyped-def]
    raw = _markdown()
    file = QuarantinedSkillFile(
        path="skills/example/SKILL.md",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        content=raw,
        media_type="text/markdown",
    )
    artifact = QuarantinedSkillArtifact(
        quarantine_id="quarantine-example",
        source_id="operations-skills",
        source_revision="a" * 40,
        artifact_digest=quarantine_artifact_digest((file,)),
        files=(file,),
        publisher_signature=b"s" * 64,
        fetched_at=NOW,
        state=SkillQuarantineState.PROPOSED,
    )
    candidate = SkillUpdateCandidate(
        candidate_id="skill-update-example",
        quarantine_id=artifact.quarantine_id,
        artifact_digest=artifact.artifact_digest,
        prior_installed_digest=None,
        created_at=NOW,
    )
    quarantine = InMemorySkillQuarantineStore()
    await quarantine.put(artifact)
    candidates = InMemorySkillUpdateCandidateStore(quarantine)
    await candidates.put(candidate)
    artifacts = ArtifactStore()
    revoker = Revoker()
    runtime_refreshes: list[None] = []

    async def refresh_runtime() -> None:
        runtime_refreshes.append(None)

    refresh = SkillSourceRefreshService(
        quarantine=quarantine,
        candidates=candidates,
        scanner=DeterministicSkillScanner(),
        verifier_factory=lambda _source, _signature: Allow(),
        scanner_version="scanner-1",
    )
    service = SkillSourceAdministrationService(
        sources=Sources(),  # type: ignore[arg-type]
        quarantine=quarantine,
        candidates=candidates,
        revocations=Revocations(),  # type: ignore[arg-type]
        refresher=refresh,
        installer=TrustedArtifactInstaller(store=artifacts),  # type: ignore[arg-type]
        verifier_factory=lambda _source, _signature: Allow(),
        revoker=revoker,
        catalog=SkillCatalog(),
        refresh_runtime=refresh_runtime,
    )
    return service, artifacts, revoker, runtime_refreshes


async def test_approve_candidate_installs_durable_artifact_disabled() -> None:
    service, artifacts, _revoker, runtime_refreshes = await _service()

    approved = await service.approve_candidate(
        source_id="operations-skills",
        candidate_id="skill-update-example",
        now=NOW,
    )

    assert approved.enabled is False
    assert approved.skill_name == "example.skill"
    assert artifacts.records[0].state is TrustedArtifactState.DISABLED
    assert runtime_refreshes == [None]


async def test_revoke_delegates_one_atomic_operation() -> None:
    service, _artifacts, revoker, runtime_refreshes = await _service()

    result = await service.revoke_source(
        source_id="operations-skills",
        reason="Publisher key was withdrawn.",
        revoked_at=NOW,
    )

    assert result.disabled_artifact_ids == ("example.skill",)
    assert revoker.calls == [("operations-skills", "Publisher key was withdrawn.", NOW)]
    assert runtime_refreshes == [None]
