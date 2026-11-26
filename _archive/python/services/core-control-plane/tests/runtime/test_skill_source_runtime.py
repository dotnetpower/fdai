"""Focused tests for skill-source runtime composition, duplicate-runner exclusion, and recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.skills import skill_body_digest
from fdai.core.skills.catalog import RuntimeSkill, SkillTrustVerifier
from fdai.core.skills.source_registry import (
    SkillSource,
    SkillSourceKind,
    SkillSourceRefreshPolicy,
    SkillSourceTrustTier,
)
from fdai.core.supply_chain.artifacts import TrustedArtifactKind, TrustedArtifactState
from fdai.core.supply_chain.skill_quarantine import SkillQuarantineState, SkillSourceRefreshState
from fdai.runtime.skill_source_runtime import (
    DuplicateSkillSourceRunnerError,
    build_skill_source_runtime_bundle,
)
from fdai.shared.providers.skill_source import (
    SkillSourceAdapter,
    SkillSourceFile,
    SkillSourceRevision,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _source(*, enabled: bool = False) -> SkillSource:
    return SkillSource(
        source_id="operations-skills",
        kind=SkillSourceKind.GITHUB_REPOSITORY,
        location="example-org/skills",
        trust_tier=SkillSourceTrustTier.ORGANIZATION_APPROVED,
        owner="platform-team",
        allowed_path="skills/example",
        authentication_audience_ref="github-app:reader",
        refresh_policy=SkillSourceRefreshPolicy.SCHEDULED,
        refresh_interval_seconds=3600,
        enabled=enabled,
    )


def _skill_markdown() -> bytes:
    body = "Verify deterministic telemetry before escalating."
    return (
        "---\n"
        "name: example.skill\n"
        "version: 1.0.0\n"
        "description: Deterministic skill.\n"
        "source: operations-skills\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        "---\n"
        f"{body}\n"
    ).encode()


class _AllowVerifier(SkillTrustVerifier):
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        del skill, raw_markdown
        return True


class _FakeAdapter(SkillSourceAdapter):
    def __init__(self) -> None:
        self.etags_seen: list[str | None] = []

    async def resolve_revision(
        self, *, repository: str, prior_etag: str | None = None
    ) -> SkillSourceRevision:
        assert repository == "example-org/skills"
        self.etags_seen.append(prior_etag)
        if prior_etag == '"etag-v1"':
            return SkillSourceRevision(revision=None, etag='"etag-v1"', not_modified=True)
        return SkillSourceRevision(revision="a" * 40, etag='"etag-v1"', not_modified=False)

    async def fetch_files(
        self, *, repository: str, revision: str, paths: tuple[str, ...]
    ) -> tuple[SkillSourceFile, ...]:
        assert repository == "example-org/skills"
        assert revision == "a" * 40
        assert paths == ("skills/example/SKILL.md", "skills/example/SKILL.md.sig")
        return (
            SkillSourceFile(
                path="skills/example/SKILL.md",
                content=_skill_markdown(),
                media_type="text/markdown",
            ),
            SkillSourceFile(
                path="skills/example/SKILL.md.sig",
                content=b"s" * 64,
                media_type="application/octet-stream",
            ),
        )


async def test_bundle_composes_refresh_approval_and_revocation_with_disabled_defaults() -> None:
    adapter = _FakeAdapter()
    refreshes: list[str] = []

    async def on_refresh_runtime() -> None:
        refreshes.append("reloaded")

    bundle = build_skill_source_runtime_bundle(
        adapter_factory=lambda _source: adapter,
        verifier_factory=lambda _source, _sig: _AllowVerifier(),
        refresh_runtime=on_refresh_runtime,
    )

    registered = await bundle.sources.put(_source(enabled=False), now=NOW)
    assert registered.enabled is False
    assert await bundle.run_scheduled_tick("runner-a", now=NOW) == ()

    await bundle.sources.set_enabled("operations-skills", enabled=True, now=NOW)
    attempts = await bundle.run_scheduled_tick("runner-a", now=NOW)
    assert len(attempts) == 1
    assert attempts[0].status == "refreshed"
    assert attempts[0].candidate_id is not None

    candidate = await bundle.candidates.get(attempts[0].candidate_id)
    assert candidate is not None
    assert candidate.disabled is True

    approved = await bundle.admin_service.approve_candidate(
        source_id="operations-skills",
        candidate_id=candidate.candidate_id,
        now=NOW + timedelta(minutes=1),
    )
    assert approved.enabled is False
    installed = await bundle.artifact_store.get(TrustedArtifactKind.SKILL, "example.skill")
    assert installed is not None
    assert installed.state is TrustedArtifactState.DISABLED

    revoked = await bundle.admin_service.revoke_source(
        source_id="operations-skills",
        reason="Emergency publisher key rotation.",
        revoked_at=NOW + timedelta(minutes=2),
    )
    assert revoked.disabled_artifact_ids == ("example.skill",)
    source_after = await bundle.sources.get("operations-skills")
    assert source_after is not None and source_after.enabled is False
    quarantined = await bundle.quarantine.list(source_id="operations-skills")
    assert quarantined[0].state is SkillQuarantineState.REVOKED
    assert len(refreshes) == 2


async def test_duplicate_runner_exclusion_and_restart_recovery() -> None:
    adapter = _FakeAdapter()
    bundle = build_skill_source_runtime_bundle(
        adapter_factory=lambda _source: adapter,
        verifier_factory=lambda _source, _sig: _AllowVerifier(),
    )
    await bundle.sources.put(_source(enabled=True), now=NOW)

    bundle.runner_guard.acquire("runner-primary", now=NOW, lease_seconds=300)
    with pytest.raises(DuplicateSkillSourceRunnerError):
        await bundle.run_scheduled_tick("runner-secondary", now=NOW + timedelta(seconds=30))

    await bundle.refresh_states.put(
        SkillSourceRefreshState(
            source_id="operations-skills",
            last_refresh_at=None,
            next_refresh_at=NOW + timedelta(minutes=5),
            last_etag='"etag-v1"',
            last_revision="a" * 40,
        )
    )

    recovery_time = NOW + timedelta(minutes=6)
    receipt = await bundle.recover_after_restart(
        "runner-recovered",
        now=recovery_time,
        lease_seconds=300,
    )
    assert receipt.reclaimed_due_source_ids == ("operations-skills",)
    assert receipt.preserved_etags == {"operations-skills": '"etag-v1"'}

    attempts = await bundle.run_scheduled_tick("runner-recovered", now=recovery_time)
    assert len(attempts) == 1
    assert attempts[0].status == "not_modified"
    assert adapter.etags_seen == ['"etag-v1"']
